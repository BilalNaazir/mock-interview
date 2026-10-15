"""
Tests for choosing which answers to share (Phase 5).
Question 1 of Backend (Python) is a knowledge question, so it counts as
answered as soon as its recording is submitted.
"""

from tests.helpers import start_attempt, submit_recording


def answered_first_question(client, s3):
    attempt_id = start_attempt(client)
    submit_recording(client, s3, attempt_id, 1)
    return attempt_id


def visibility_of(client, attempt_id, order):
    return client.get(f"/attempts/{attempt_id}").json()["questions"][order - 1]["visibility"]


def test_answers_are_private_by_default(logged_in_client, s3):
    attempt_id = answered_first_question(logged_in_client, s3)
    assert visibility_of(logged_in_client, attempt_id, 1) == "private"


def test_an_answer_can_be_shared_and_made_private_again(logged_in_client, s3):
    attempt_id = answered_first_question(logged_in_client, s3)
    url = f"/attempts/{attempt_id}/questions/1/visibility"

    assert logged_in_client.put(url, json={"visibility": "shared"}).json() == {"visibility": "shared", "changed": 1}
    assert visibility_of(logged_in_client, attempt_id, 1) == "shared"

    logged_in_client.put(url, json={"visibility": "private"})
    assert visibility_of(logged_in_client, attempt_id, 1) == "private"


def test_unanswered_questions_cannot_be_shared(logged_in_client, s3):
    attempt_id = answered_first_question(logged_in_client, s3)
    response = logged_in_client.put(f"/attempts/{attempt_id}/questions/2/visibility", json={"visibility": "shared"})
    assert response.status_code == 404


def test_only_the_owner_can_share(logged_in_client, other_user_client, s3):
    attempt_id = answered_first_question(logged_in_client, s3)
    response = other_user_client.put(f"/attempts/{attempt_id}/questions/1/visibility", json={"visibility": "shared"})
    assert response.status_code == 404
    assert visibility_of(logged_in_client, attempt_id, 1) == "private"


def test_share_everything_in_an_interview_at_once(logged_in_client, s3):
    attempt_id = start_attempt(logged_in_client)
    for order in (1, 2, 3):
        submit_recording(logged_in_client, s3, attempt_id, order)

    response = logged_in_client.put(f"/attempts/{attempt_id}/visibility", json={"visibility": "shared"})
    assert response.json()["changed"] == 3
    assert [visibility_of(logged_in_client, attempt_id, order) for order in (1, 2, 3)] == ["shared"] * 3


def test_only_private_or_shared_are_allowed(logged_in_client, s3):
    attempt_id = answered_first_question(logged_in_client, s3)
    response = logged_in_client.put(f"/attempts/{attempt_id}/questions/1/visibility", json={"visibility": "public"})
    assert response.status_code == 422  # rejected by the Visibility type in models.py
