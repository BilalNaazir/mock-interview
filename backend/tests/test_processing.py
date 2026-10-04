"""
Tests for the worker: taking a job off the queue and processing it.

Whisper and Claude are replaced with fakes, so these tests are fast, free,
and don't need a 150 MB model or an API key. The REAL queue code, S3 code
and database code all run (against the fake AWS and the test database).
"""

import os
from urllib.parse import urlparse

import pytest
from pymongo import MongoClient

from app.config import get_settings
from app.processing import WorkerContext, handle_job
from app.queue import JobQueue
from app.scoring import Evaluation
from app.storage import VideoStorage

FAKE_VIDEO = b"pretend video" * 50


class FakeTranscriber:
    def __init__(self, text="I would use async endpoints for non-blocking work.", fail=False):
        self.text, self.fail, self.calls = text, fail, 0

    def transcribe(self, media_path):
        self.calls += 1
        assert os.path.getsize(media_path) == len(FAKE_VIDEO)  # the real video was downloaded
        if self.fail:
            raise RuntimeError("Whisper crashed")
        return self.text


class FakeScorer:
    def __init__(self):
        self.calls = []

    def score_knowledge_answer(self, question, key_points, transcript):
        self.calls.append({"question": question, "key_points": key_points, "transcript": transcript})
        return Evaluation(
            score=75, covered_points=key_points[:2], missing_points=key_points[2:], feedback="Good start."
        )


@pytest.fixture
def db():
    client = MongoClient(os.environ["MONGODB_URI"])
    yield client["mock_interview_test"]
    client.close()


def make_context(db, transcriber=None, scorer=None):
    settings = get_settings()
    return WorkerContext(
        db=db,
        storage=VideoStorage(settings),
        transcriber=transcriber or FakeTranscriber(),
        scorer=scorer or FakeScorer(),
        settings=settings,
    )


def answer_questions(client, s3, up_to):
    """Use the real API to answer questions 1..up_to, like a user would."""
    attempt_id = client.post(
        "/attempts", json={"interview_slug": "backend-python", "consent_to_recording": True}
    ).json()["attempt_id"]
    for order in range(1, up_to + 1):
        ticket = client.post(
            f"/attempts/{attempt_id}/questions/{order}/upload-url",
            json={"content_type": "video/webm", "size_bytes": len(FAKE_VIDEO)},
        ).json()
        key = urlparse(ticket["upload_url"]).path.lstrip("/")
        s3.put_object(Bucket="test-videos-bucket", Key=key, Body=FAKE_VIDEO, ContentType="video/webm")
        client.post(f"/attempts/{attempt_id}/questions/{order}/recordings/{ticket['recording_id']}/complete")
    return attempt_id


def next_job():
    jobs = JobQueue(get_settings()).receive_jobs(visibility_timeout=0)
    assert jobs, "expected a job on the queue"
    return jobs[0]


# ---------------------------------------------------------------------------

def test_submitting_an_answer_puts_a_job_on_the_queue(logged_in_client, s3):
    attempt_id = answer_questions(logged_in_client, s3, up_to=1)
    job = next_job()
    assert job.body["type"] == "process_recording"
    assert logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]["processing_status"] == "queued"


def test_knowledge_answer_is_transcribed_and_scored(logged_in_client, s3, db):
    attempt_id = answer_questions(logged_in_client, s3, up_to=1)
    scorer = FakeScorer()

    assert handle_job(next_job(), make_context(db, scorer=scorer)) is True  # True = delete the job

    # Claude received the question, the PRIVATE rubric, and the transcript.
    [call] = scorer.calls
    assert call["transcript"] == "I would use async endpoints for non-blocking work."
    assert len(call["key_points"]) == 4

    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "done"
    assert question["transcript"] == "I would use async endpoints for non-blocking work."
    assert question["evaluation"]["score"] == 75
    assert question["evaluation"]["feedback"] == "Good start."


def test_situational_answer_is_transcribed_but_not_scored_yet(logged_in_client, s3, db):
    attempt_id = answer_questions(logged_in_client, s3, up_to=4)
    scorer = FakeScorer()
    ctx = make_context(db, scorer=scorer)
    queue = JobQueue(get_settings())
    for _ in range(4):
        job = next_job()
        assert handle_job(job, ctx) is True
        # Like the real worker loop: a finished job must be DELETED, or SQS
        # will hand the same job out again.
        queue.delete_job(job)

    question_4 = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][3]
    assert question_4["type"] == "situational"
    assert question_4["processing_status"] == "done"
    assert question_4["transcript"] is not None
    assert question_4["evaluation"] is None  # STAR evaluation arrives in Phase 4
    assert len(scorer.calls) == 3  # only the three knowledge answers were scored


def test_the_same_job_twice_is_only_processed_once(logged_in_client, s3, db):
    answer_questions(logged_in_client, s3, up_to=1)
    job = next_job()
    transcriber, scorer = FakeTranscriber(), FakeScorer()
    ctx = make_context(db, transcriber=transcriber, scorer=scorer)

    assert handle_job(job, ctx) is True
    assert handle_job(job, ctx) is True  # e.g. SQS delivered it twice
    assert transcriber.calls == 1 and len(scorer.calls) == 1  # no double charges


def test_a_failed_job_is_kept_for_a_retry(logged_in_client, s3, db):
    attempt_id = answer_questions(logged_in_client, s3, up_to=1)
    job = next_job()
    job.receive_count = 1

    assert handle_job(job, make_context(db, transcriber=FakeTranscriber(fail=True))) is False  # NOT deleted
    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "queued"


def test_after_the_last_try_the_answer_is_marked_failed(logged_in_client, s3, db):
    attempt_id = answer_questions(logged_in_client, s3, up_to=1)
    job = next_job()
    job.receive_count = 3  # the third delivery - the last one allowed

    # Still not deleted: SQS moves it to the dead-letter queue for inspection.
    assert handle_job(job, make_context(db, transcriber=FakeTranscriber(fail=True))) is False
    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "failed"


def test_a_job_for_a_deleted_answer_is_dropped(db):
    from app.queue import ReceivedJob

    job = ReceivedJob(
        body={"answer_id": "0123456789abcdef01234567", "recording_id": "x"}, receipt_handle="r", receive_count=1
    )
    assert handle_job(job, make_context(db)) is True  # nothing to do, so delete it


def test_without_a_queue_answers_are_stored_but_not_processed(logged_in_client, s3):
    from app.queue import JobQueue, get_queue

    settings = get_settings().model_copy(update={"sqs_processing_queue_url": ""})
    logged_in_client.app.dependency_overrides[get_queue] = lambda: JobQueue(settings)
    attempt_id = answer_questions(logged_in_client, s3, up_to=1)

    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["answered"] is True
    assert question["processing_status"] == "not_configured"
