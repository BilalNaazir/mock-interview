"""
Tests for taking an interview: starting, uploading answers, and playback.

"Uploading" here is done with the fake S3 from conftest.py: we put the file
in the bucket ourselves, exactly as the browser would with the presigned URL.
"""

from urllib.parse import parse_qs, urlparse

import pytest

FAKE_VIDEO = b"pretend this is a video" * 100


def start(client, slug="backend-python"):
    response = client.post("/attempts", json={"interview_slug": slug, "consent_to_recording": True})
    assert response.status_code == 201, response.text
    return response.json()["attempt_id"]


def request_upload(client, attempt_id, order, content_type="video/webm", size=len(FAKE_VIDEO)):
    return client.post(
        f"/attempts/{attempt_id}/questions/{order}/upload-url",
        json={"content_type": content_type, "size_bytes": size},
    )


def answer_question(client, s3, attempt_id, order, body=FAKE_VIDEO, content_type="video/webm"):
    """The full browser flow for one question: get URL -> upload -> complete."""
    ticket = request_upload(client, attempt_id, order, content_type=content_type).json()
    key = urlparse(ticket["upload_url"]).path.lstrip("/")
    s3.put_object(Bucket="test-videos-bucket", Key=key, Body=body, ContentType=content_type)
    return client.post(f"/attempts/{attempt_id}/questions/{order}/recordings/{ticket['recording_id']}/complete")


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------

def test_starting_requires_login(client):
    response = client.post("/attempts", json={"interview_slug": "backend-python", "consent_to_recording": True})
    assert response.status_code == 401


def test_starting_requires_consent(logged_in_client):
    response = logged_in_client.post(
        "/attempts", json={"interview_slug": "backend-python", "consent_to_recording": False}
    )
    assert response.status_code == 400


def test_starting_an_unknown_interview_fails(logged_in_client):
    response = logged_in_client.post("/attempts", json={"interview_slug": "nope", "consent_to_recording": True})
    assert response.status_code == 404


def test_starting_again_resumes_the_unfinished_attempt(logged_in_client):
    first = start(logged_in_client)
    second = logged_in_client.post(
        "/attempts", json={"interview_slug": "backend-python", "consent_to_recording": True}
    ).json()
    assert second == {"attempt_id": first, "resumed": True}


def test_new_attempt_starts_at_question_1(logged_in_client):
    attempt = logged_in_client.get(f"/attempts/{start(logged_in_client)}").json()
    assert attempt["status"] == "in_progress"
    assert attempt["current_question"] == 1
    assert [q["answered"] for q in attempt["questions"]] == [False] * 5
    assert attempt["limits"]["max_recording_seconds"] == 180
    assert "key_points" not in attempt["questions"][0]  # the rubric stays private


# ---------------------------------------------------------------------------
# The full happy path
# ---------------------------------------------------------------------------

def test_answering_all_five_questions_completes_the_attempt(logged_in_client, s3):
    attempt_id = start(logged_in_client)

    for order in range(1, 6):
        response = answer_question(logged_in_client, s3, attempt_id, order)
        assert response.status_code == 200, response.text
        assert response.json()["current_question"] == order + 1

    attempt = logged_in_client.get(f"/attempts/{attempt_id}").json()
    assert attempt["status"] == "completed"
    assert all(q["answered"] for q in attempt["questions"])

    [summary] = logged_in_client.get("/attempts").json()
    assert summary["answered_count"] == 5
    assert summary["status"] == "completed"


def test_finished_interview_cannot_be_answered_again(logged_in_client, s3):
    attempt_id = start(logged_in_client)
    for order in range(1, 6):
        answer_question(logged_in_client, s3, attempt_id, order)
    assert request_upload(logged_in_client, attempt_id, 5).status_code == 409


# ---------------------------------------------------------------------------
# The presigned upload URL
# ---------------------------------------------------------------------------

def test_upload_url_locks_in_type_and_size(logged_in_client):
    ticket = request_upload(logged_in_client, start(logged_in_client), 1).json()
    url = urlparse(ticket["upload_url"])
    query = parse_qs(url.query)

    # The bucket's own regional address (avoids redirects that break uploads).
    assert url.netloc == "test-videos-bucket.s3.eu-north-1.amazonaws.com"
    # Content type and size are part of the signature, so S3 enforces them.
    assert query["X-Amz-SignedHeaders"] == ["content-length;content-type;host"]
    assert ticket["upload_headers"] == {"Content-Type": "video/webm"}


def test_codec_details_in_the_content_type_are_accepted(logged_in_client):
    response = request_upload(logged_in_client, start(logged_in_client), 1, content_type="video/webm;codecs=vp9,opus")
    assert response.status_code == 200
    assert response.json()["upload_headers"] == {"Content-Type": "video/webm"}


@pytest.mark.parametrize("content_type", ["image/png", "application/pdf", "text/html"])
def test_non_video_files_are_rejected(logged_in_client, content_type):
    response = request_upload(logged_in_client, start(logged_in_client), 1, content_type=content_type)
    assert response.status_code == 400


def test_oversized_recordings_are_rejected(logged_in_client):
    response = request_upload(logged_in_client, start(logged_in_client), 1, size=101 * 1024 * 1024)
    assert response.status_code == 413


def test_questions_must_be_answered_in_order(logged_in_client):
    response = request_upload(logged_in_client, start(logged_in_client), 2)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Completing an upload
# ---------------------------------------------------------------------------

def test_completing_before_uploading_fails(logged_in_client):
    attempt_id = start(logged_in_client)
    ticket = request_upload(logged_in_client, attempt_id, 1).json()

    response = logged_in_client.post(
        f"/attempts/{attempt_id}/questions/1/recordings/{ticket['recording_id']}/complete"
    )
    assert response.status_code == 400
    assert logged_in_client.get(f"/attempts/{attempt_id}").json()["current_question"] == 1


def test_a_file_that_does_not_match_is_rejected_and_deleted(logged_in_client, s3):
    attempt_id = start(logged_in_client)
    ticket = request_upload(logged_in_client, attempt_id, 1).json()
    key = urlparse(ticket["upload_url"]).path.lstrip("/")
    # Pretend something sneaky happened: a different-sized file arrived.
    s3.put_object(Bucket="test-videos-bucket", Key=key, Body=b"surprise", ContentType="video/webm")

    response = logged_in_client.post(
        f"/attempts/{attempt_id}/questions/1/recordings/{ticket['recording_id']}/complete"
    )
    assert response.status_code == 400
    assert s3.list_objects_v2(Bucket="test-videos-bucket").get("KeyCount") == 0


def test_completing_twice_only_moves_forward_once(logged_in_client, s3):
    attempt_id = start(logged_in_client)
    ticket = request_upload(logged_in_client, attempt_id, 1).json()
    key = urlparse(ticket["upload_url"]).path.lstrip("/")
    s3.put_object(Bucket="test-videos-bucket", Key=key, Body=FAKE_VIDEO, ContentType="video/webm")
    complete_url = f"/attempts/{attempt_id}/questions/1/recordings/{ticket['recording_id']}/complete"

    first = logged_in_client.post(complete_url).json()
    second = logged_in_client.post(complete_url).json()
    assert first == second == {"status": "in_progress", "current_question": 2}


def test_retrying_an_upload_replaces_the_unfinished_recording(logged_in_client):
    attempt_id = start(logged_in_client)
    old = request_upload(logged_in_client, attempt_id, 1).json()
    new = request_upload(logged_in_client, attempt_id, 1).json()
    assert old["recording_id"] != new["recording_id"]

    response = logged_in_client.post(
        f"/attempts/{attempt_id}/questions/1/recordings/{old['recording_id']}/complete"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Privacy: nobody can touch someone else's interview
# ---------------------------------------------------------------------------

def test_other_users_cannot_see_or_change_my_attempt(logged_in_client, other_user_client, s3):
    attempt_id = start(logged_in_client)
    answer_question(logged_in_client, s3, attempt_id, 1)

    assert other_user_client.get(f"/attempts/{attempt_id}").status_code == 404
    assert request_upload(other_user_client, attempt_id, 2).status_code == 404
    assert other_user_client.get(f"/attempts/{attempt_id}/questions/1/video-url").status_code == 404
    assert other_user_client.get("/attempts").json() == []


def test_nonsense_ids_return_404(logged_in_client):
    assert logged_in_client.get("/attempts/not-a-real-id").status_code == 404


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def test_video_url_only_exists_once_answered(logged_in_client, s3):
    attempt_id = start(logged_in_client)
    assert logged_in_client.get(f"/attempts/{attempt_id}/questions/1/video-url").status_code == 404

    answer_question(logged_in_client, s3, attempt_id, 1, content_type="video/mp4")
    video = logged_in_client.get(f"/attempts/{attempt_id}/questions/1/video-url").json()

    assert video["content_type"] == "video/mp4"
    assert ".mp4?" in video["url"]
    assert "X-Amz-Signature" in video["url"]  # a signed, temporary link


def test_uploads_are_unavailable_when_no_bucket_is_configured(logged_in_client):
    from app.config import get_settings
    from app.storage import VideoStorage, get_storage

    settings = get_settings().model_copy(update={"s3_videos_bucket": ""})
    logged_in_client.app.dependency_overrides[get_storage] = lambda: VideoStorage(settings)

    response = request_upload(logged_in_client, start(logged_in_client), 1)
    assert response.status_code == 503
