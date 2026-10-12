"""
Tests for the worker: taking a job off the queue and processing it.

Whisper and Claude are replaced with fakes (see helpers.py), so these tests
are fast, free, and don't need a 150 MB model or an API key. The REAL queue
code, S3 code and database code all run (against the fake AWS and the test
database). Follow-up questions have their own file: test_follow_ups.py.
"""

from app.config import get_settings
from app.processing import handle_job
from app.queue import JobQueue, ReceivedJob
from tests.helpers import FakeScorer, FakeTranscriber, make_worker_context, start_attempt, submit_recording


def next_job():
    jobs = JobQueue(get_settings()).receive_jobs(visibility_timeout=0, wait_seconds=0)
    assert jobs, "expected a job on the queue"
    return jobs[0]


def answer_first_question(client, s3):
    attempt_id = start_attempt(client)
    submit_recording(client, s3, attempt_id, 1)
    return attempt_id


def test_submitting_an_answer_puts_a_job_on_the_queue(logged_in_client, s3):
    attempt_id = answer_first_question(logged_in_client, s3)
    job = next_job()
    assert job.body["type"] == "process_recording"
    assert logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]["processing_status"] == "queued"


def test_knowledge_answer_is_transcribed_and_scored(logged_in_client, s3, db):
    attempt_id = answer_first_question(logged_in_client, s3)
    scorer = FakeScorer()

    assert handle_job(next_job(), make_worker_context(db, scorer=scorer)) is True  # True = delete the job

    # Claude received the question, the PRIVATE rubric, and the transcript.
    [call] = scorer.knowledge_calls
    assert call["transcript"] == "I would use async endpoints for non-blocking work."
    assert len(call["key_points"]) == 4

    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "done"
    assert question["transcript"] == "I would use async endpoints for non-blocking work."
    assert question["evaluation"]["kind"] == "knowledge"
    assert question["evaluation"]["score"] == 75
    assert question["evaluation"]["feedback"] == "Good start."


def test_knowledge_answers_do_not_hold_up_the_interview(logged_in_client, s3):
    attempt_id = answer_first_question(logged_in_client, s3)
    # Not processed yet, but we've already moved on to question 2.
    attempt = logged_in_client.get(f"/attempts/{attempt_id}").json()
    assert attempt["current_question"] == 2
    assert attempt["current_step"] == "record_answer"


def test_the_same_job_twice_is_only_processed_once(logged_in_client, s3, db):
    answer_first_question(logged_in_client, s3)
    job = next_job()
    transcriber, scorer = FakeTranscriber(), FakeScorer()
    ctx = make_worker_context(db, transcriber=transcriber, scorer=scorer)

    assert handle_job(job, ctx) is True
    assert handle_job(job, ctx) is True  # e.g. SQS delivered it twice
    assert transcriber.calls == 1 and len(scorer.knowledge_calls) == 1  # no double charges


def test_a_failed_job_is_kept_for_a_retry(logged_in_client, s3, db):
    attempt_id = answer_first_question(logged_in_client, s3)
    job = next_job()
    job.receive_count = 1

    assert handle_job(job, make_worker_context(db, transcriber=FakeTranscriber(fail=True))) is False  # NOT deleted
    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "queued"


def test_after_the_last_try_the_answer_is_marked_failed(logged_in_client, s3, db):
    attempt_id = answer_first_question(logged_in_client, s3)
    job = next_job()
    job.receive_count = 3  # the third delivery - the last one allowed

    # Still not deleted: SQS moves it to the dead-letter queue for inspection.
    assert handle_job(job, make_worker_context(db, transcriber=FakeTranscriber(fail=True))) is False
    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["processing_status"] == "failed"


def test_a_job_for_a_deleted_answer_is_dropped(db):
    job = ReceivedJob(
        body={"answer_id": "0123456789abcdef01234567", "recording_id": "x"}, receipt_handle="r", receive_count=1
    )
    assert handle_job(job, make_worker_context(db)) is True  # nothing to do, so delete it


def test_without_a_queue_answers_are_stored_but_not_processed(logged_in_client, s3):
    from app.queue import get_queue

    settings = get_settings().model_copy(update={"sqs_processing_queue_url": ""})
    logged_in_client.app.dependency_overrides[get_queue] = lambda: JobQueue(settings)
    attempt_id = answer_first_question(logged_in_client, s3)

    question = logged_in_client.get(f"/attempts/{attempt_id}").json()["questions"][0]
    assert question["answered"] is True
    assert question["processing_status"] == "not_configured"
