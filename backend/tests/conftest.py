"""
conftest.py - Shared setup for all tests (pytest loads this automatically).

Tests run against a REAL MongoDB (from Docker Compose locally, or a service
container in GitHub Actions), but in a separate "mock_interview_test"
database that gets wiped afterwards - so tests never touch your dev data.
"""

import os

# These must be set BEFORE the app is imported, because the settings are
# read at import time. Values here are fakes, safe to commit.
os.environ["ENVIRONMENT"] = "dev"
os.environ["MONGODB_DB_NAME"] = "mock_interview_test"
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ["COGNITO_USER_POOL_ID"] = "eu-west-2_TestPool"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id"
os.environ["COGNITO_DOMAIN"] = "https://test.auth.eu-west-2.amazoncognito.com"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.auth import get_current_user  # noqa: E402
from app.main import create_app  # noqa: E402

FAKE_USER = {
    "cognito_sub": "test-user-123",
    "email": "tester@example.com",
    "name": "Test User",
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


@pytest.fixture
def client():
    """A test client for an app where nobody is logged in."""
    app = create_app()
    # `with` runs the app's startup code (connect to Mongo, seed) and shutdown.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def logged_in_client():
    """
    A test client where every request counts as FAKE_USER.
    dependency_overrides swaps the real login check for a function that just
    returns our fake user, so tests don't need real Cognito tokens.
    Real token checking is tested separately in test_auth.py.
    """
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with TestClient(app) as test_client:
        yield test_client
