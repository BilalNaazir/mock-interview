"""
conftest.py - Shared setup for all tests (pytest loads this automatically).

Tests run against a REAL MongoDB (from Docker Compose locally, or a service
container in GitHub Actions), but in a separate "mock_interview_test"
database that gets wiped afterwards - so tests never touch your dev data.

S3 and SQS are FAKED with moto: it pretends to be AWS, entirely in memory.
So the tests never touch your real bucket or queue, cost nothing, and need
no AWS keys.
"""

import os

# These must be set BEFORE the app is imported, because the settings are
# read at import time. Values here are fakes, safe to commit.
os.environ["ENVIRONMENT"] = "dev"
os.environ["MONGODB_DB_NAME"] = "mock_interview_test"
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ["COGNITO_REGION"] = "eu-north-1"
os.environ["COGNITO_USER_POOL_ID"] = "eu-north-1_TestPool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"
os.environ["COGNITO_DOMAIN"] = "https://test.auth.eu-north-1.amazoncognito.com"
os.environ["AWS_REGION"] = "eu-north-1"
os.environ["S3_VIDEOS_BUCKET"] = "test-videos-bucket"
# moto's fake AWS uses the account ID 123456789012.
os.environ["SQS_PROCESSING_QUEUE_URL"] = "https://sqs.eu-north-1.amazonaws.com/123456789012/test-processing"
# Make the WebSocket check for changes very often, so tests run fast.
os.environ["WS_POLL_INTERVAL_SECONDS"] = "0.05"
os.environ["WS_AUTH_TIMEOUT_SECONDS"] = "0.5"
# Fake AWS keys. moto accepts anything; these guarantee that even a mistake
# could never use your real AWS account from a test.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"

import boto3  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from moto import mock_aws  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.auth import get_current_user  # noqa: E402
from app.main import create_app  # noqa: E402

FAKE_USER = {
    "cognito_sub": "test-user-123",
    "email": "tester@example.com",
    "name": "Test User",
    "share_answers_by_default": False,
}

OTHER_USER = {
    "cognito_sub": "someone-else-456",
    "email": "other@example.com",
    "name": "Other User",
    "share_answers_by_default": False,
}


@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    """Wipe the test database before and after the whole test run."""
    client = MongoClient(os.environ["MONGODB_URI"])
    client.drop_database("mock_interview_test")
    yield
    client.drop_database("mock_interview_test")
    client.close()


@pytest.fixture(autouse=True)
def fresh_attempts():
    """Each test starts with no attempts or answers, so tests can't affect each other."""
    client = MongoClient(os.environ["MONGODB_URI"])
    db = client["mock_interview_test"]
    db.attempts.delete_many({})
    db.answers.delete_many({})
    yield
    client.close()


@pytest.fixture(autouse=True)
def s3():
    """
    Turn on the fake AWS for every test, with an empty videos bucket.
    The S3 client returned here lets tests act like the browser - e.g. put a
    file in the bucket, as if it had been uploaded with a presigned URL.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="eu-north-1")
        client.create_bucket(
            Bucket="test-videos-bucket",
            CreateBucketConfiguration={"LocationConstraint": "eu-north-1"},
        )
        yield client


@pytest.fixture(autouse=True)
def sqs(s3):
    """A fake, empty processing queue (inside the same fake AWS as s3)."""
    client = boto3.client("sqs", region_name="eu-north-1")
    client.create_queue(QueueName="test-processing")
    yield client


def make_client(user: dict | None):
    app = create_app()
    if user is not None:
        # Swap the real login check for one that returns this fake user, so
        # tests don't need real Cognito tokens. Real token checking is tested
        # separately in test_auth.py.
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def client():
    """A test client where nobody is logged in."""
    # `with` runs the app's startup code (connect to Mongo, seed) and shutdown.
    with make_client(None) as test_client:
        yield test_client


@pytest.fixture
def logged_in_client():
    """A test client where every request counts as FAKE_USER."""
    with make_client(FAKE_USER) as test_client:
        yield test_client


@pytest.fixture
def other_user_client():
    """A second, different logged-in user - for checking people can't see each other's data."""
    with make_client(OTHER_USER) as test_client:
        yield test_client
