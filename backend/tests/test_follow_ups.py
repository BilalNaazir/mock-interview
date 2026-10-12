"""
Tests for situational questions: STAR checks and follow-up questions.

In the Backend (Python) interview, questions 4 and 5 are situational.
Each test first answers questions 1-3, so question 4 is the current one.
"""

import pytest

from app.config import get_settings
from app.processing import handle_job
from app.queue import JobQueue
from tests.helpers import (
    ALL_CLEAR,
    FakeScorer,
    FakeTranscriber,
    make_worker_context,
    run_worker,
    start_attempt,
    submit_recording,
)

MISSING_RESULT = {"situation": "clear", "task": "clear", "action": "clear", "result": "missing"}


@pytest.fixture
def at_question_4(logged_in_client, s3, db):
    """An attempt with the three knowledge questions answered and processed."""
    attempt_id = start_attempt(logged_in_client)
    for order in (1, 2, 3):
        submit_recording(logged_in_client, s3, attempt_id, order)
    run_worker(make_worker_context(db))
    return attempt_id


def get(client, attempt_id):
    return client.get(f"/attempts/{attempt_id}").json()


# ---------------------------------------------------------------------------
# Waiting for the STAR check
# ---------------------------------------------------------------------------

def test_a_situational_answer_waits_for_its_star_check(logged_in_client, s3, at_question_4):
    response = submit_recording(logged_in_client, s3, at_question_4, 4)
    assert response.json()["current_question"] == 4  # NOT moved on yet

    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_step"] == "evaluating"
    assert attempt["questions"][3]["answered"] is False


def test_you_cannot_record_again_while_being_evaluated(logged_in_client, s3, at_question_4):
    submit_recording(logged_in_client, s3, at_question_4, 4)
    response = logged_in_client.post(
        f"/attempts/{at_question_4}/questions/4/upload-url", json={"content_type": "video/webm", "size_bytes": 100}
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# A complete answer is accepted
# ---------------------------------------------------------------------------

def test_a_complete_star_answer_is_accepted_without_follow_ups(logged_in_client, s3, db, at_question_4):
    submit_recording(logged_in_client, s3, at_question_4, 4)
    run_worker(make_worker_context(db, scorer=FakeScorer(star_ratings=[ALL_CLEAR])))

    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 5
    assert attempt["current_step"] == "record_answer"
    question = attempt["questions"][3]
    assert question["answered"] is True
    assert question["follow_ups"] == []
    assert question["evaluation"]["kind"] == "star"
    assert question["evaluation"]["score"] == 100


def test_the_score_is_worked_out_from_the_ratings(logged_in_client, s3, db, at_question_4):
    submit_recording(logged_in_client, s3, at_question_4, 4)
    ratings = {"situation": "clear", "task": "partial", "action": "missing", "result": "clear"}
    # No follow-up text, so the answer is accepted as it is.
    run_worker(make_worker_context(db, scorer=FakeScorer(star_ratings=[ratings], follow_up_text="")))

    evaluation = get(logged_in_client, at_question_4)["questions"][3]["evaluation"]
    assert evaluation["score"] == 25 + 12 + 0 + 25
    assert evaluation["task"] == {"rating": "partial", "comment": "task was partial"}


# ---------------------------------------------------------------------------
# Follow-up questions
# ---------------------------------------------------------------------------

def test_a_missing_element_triggers_a_follow_up_question(logged_in_client, s3, db, at_question_4):
    submit_recording(logged_in_client, s3, at_question_4, 4)
    scorer = FakeScorer(star_ratings=[MISSING_RESULT], follow_up_text="How did it turn out in the end?")
    run_worker(make_worker_context(db, scorer=scorer))

    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 4  # still on this question
    assert attempt["current_step"] == "record_follow_up"
    assert attempt["pending_follow_up"] == {"number": 1, "question": "How did it turn out in the end?"}
    assert attempt["questions"][3]["follow_ups"][0]["answered"] is False


def test_answering_the_follow_up_completes_the_question(logged_in_client, s3, db, at_question_4):
    scorer = FakeScorer(star_ratings=[MISSING_RESULT, ALL_CLEAR])
    transcriber = FakeTranscriber(texts=["We had a slow API and I added caching.", "Response times halved."])
    worker = make_worker_context(db, transcriber=transcriber, scorer=scorer)

    submit_recording(logged_in_client, s3, at_question_4, 4)  # main answer
    run_worker(worker)                                         # -> follow-up asked

    ticket = logged_in_client.post(
        f"/attempts/{at_question_4}/questions/4/upload-url", json={"content_type": "video/webm", "size_bytes": 10}
    ).json()
    assert ticket["kind"] == "follow_up" and ticket["follow_up_number"] == 1
    assert "/q4-followup1-" in ticket["upload_url"]  # the file name says what it is

    submit_recording(logged_in_client, s3, at_question_4, 4)  # the follow-up answer
    assert get(logged_in_client, at_question_4)["current_step"] == "evaluating"
    run_worker(worker)                                         # -> accepted

    # The second STAR check saw the WHOLE conversation, not just the last bit.
    second_check = scorer.star_calls[1]
    assert [e.transcript for e in second_check] == [
        "We had a slow API and I added caching.",
        "Response times halved.",
    ]
    assert second_check[1].question == "Can you tell me more about that?"

    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 5
    follow_up = attempt["questions"][3]["follow_ups"][0]
    assert follow_up["answered"] is True
    assert follow_up["transcript"] == "Response times halved."


def test_no_more_than_three_follow_ups_however_unclear(logged_in_client, s3, db, at_question_4):
    # This fake Claude is NEVER satisfied, and always wants another follow-up.
    scorer = FakeScorer(star_ratings=[MISSING_RESULT] * 10)
    worker = make_worker_context(db, scorer=scorer)

    submit_recording(logged_in_client, s3, at_question_4, 4)
    run_worker(worker)
    for _ in range(3):
        assert get(logged_in_client, at_question_4)["current_step"] == "record_follow_up"
        submit_recording(logged_in_client, s3, at_question_4, 4)
        run_worker(worker)

    # Our code stopped it at 3, and the interview moved on.
    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 5
    assert len(attempt["questions"][3]["follow_ups"]) == 3
    assert len(scorer.star_calls) == 4  # the main answer + 3 follow-ups


def test_follow_up_answers_can_be_played_back(logged_in_client, s3, db, at_question_4):
    worker = make_worker_context(db, scorer=FakeScorer(star_ratings=[MISSING_RESULT, ALL_CLEAR]))
    submit_recording(logged_in_client, s3, at_question_4, 4)
    run_worker(worker)
    submit_recording(logged_in_client, s3, at_question_4, 4)
    run_worker(worker)

    follow_up = get(logged_in_client, at_question_4)["questions"][3]["follow_ups"][0]
    response = logged_in_client.get(
        f"/attempts/{at_question_4}/questions/4/video-url", params={"recording_id": follow_up["recording_id"]}
    )
    assert response.status_code == 200
    assert "q4-followup1-" in response.json()["url"]


# ---------------------------------------------------------------------------
# Nobody gets stuck
# ---------------------------------------------------------------------------

def test_if_evaluation_keeps_failing_the_answer_is_accepted(logged_in_client, s3, db, at_question_4):
    submit_recording(logged_in_client, s3, at_question_4, 4)
    job = JobQueue(get_settings()).receive_jobs(visibility_timeout=0, wait_seconds=0)[0]
    job.receive_count = 3  # the last try

    handle_job(job, make_worker_context(db, transcriber=FakeTranscriber(fail=True)))

    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 5  # moved on, not stuck forever
    assert attempt["questions"][3]["processing_status"] == "failed"


def test_without_a_queue_situational_answers_are_accepted_straight_away(logged_in_client, s3, at_question_4):
    from app.queue import get_queue

    settings = get_settings().model_copy(update={"sqs_processing_queue_url": ""})
    logged_in_client.app.dependency_overrides[get_queue] = lambda: JobQueue(settings)

    submit_recording(logged_in_client, s3, at_question_4, 4)
    attempt = get(logged_in_client, at_question_4)
    assert attempt["current_question"] == 5
    assert attempt["questions"][3]["answered"] is True
