"""
helpers.py - Fakes and shortcuts shared by several test files.

  - FakeTranscriber stands in for Whisper (no 150 MB model needed)
  - FakeScorer stands in for Claude (no API key, no cost)
  - submit_recording() does what the browser does for one recording
  - run_worker() does what the worker does, until the queue is empty
"""

from urllib.parse import urlparse

from app.config import get_settings
from app.processing import WorkerContext, handle_job
from app.queue import JobQueue
from app.scoring import Evaluation, StarElement, StarEvaluation
from app.storage import VideoStorage

FAKE_VIDEO = b"pretend video" * 50
ALL_CLEAR = {"situation": "clear", "task": "clear", "action": "clear", "result": "clear"}


class FakeTranscriber:
    """Returns pretend transcripts: the given ones in order, then a default."""

    def __init__(self, texts=None, fail=False):
        self.texts = list(texts or [])
        self.fail = fail
        self.calls = 0

    def transcribe(self, media_path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Whisper crashed")
        return self.texts.pop(0) if self.texts else "I would use async endpoints for non-blocking work."


class FakeScorer:
    """
    Pretend Claude. For STAR checks, `star_ratings` is a list of ratings to
    return, one per check, in order; when it runs out, everything is clear.
    """

    def __init__(self, star_ratings=None, follow_up_text="Can you tell me more about that?"):
        self.knowledge_calls = []
        self.star_calls = []
        self.star_ratings = list(star_ratings or [])
        self.follow_up_text = follow_up_text

    def score_knowledge_answer(self, question, key_points, transcript):
        self.knowledge_calls.append({"question": question, "key_points": key_points, "transcript": transcript})
        return Evaluation(
            score=75, covered_points=key_points[:2], missing_points=key_points[2:], feedback="Good start."
        )

    def evaluate_star(self, exchanges):
        self.star_calls.append(exchanges)
        ratings = self.star_ratings.pop(0) if self.star_ratings else ALL_CLEAR
        all_clear = all(rating == "clear" for rating in ratings.values())
        elements = {
            element: StarElement(rating=rating, comment=f"{element} was {rating}")
            for element, rating in ratings.items()
        }
        return StarEvaluation(
            **elements,
            feedback="Nice story.",
            follow_up_question="" if all_clear else self.follow_up_text,
        )


def start_attempt(client, slug="backend-python"):
    response = client.post("/attempts", json={"interview_slug": slug, "consent_to_recording": True})
    assert response.status_code == 201, response.text
    return response.json()["attempt_id"]


def submit_recording(client, s3, attempt_id, order, body=FAKE_VIDEO, content_type="video/webm"):
    """What the browser does for one recording: get a URL, upload, then say 'done'."""
    response = client.post(
        f"/attempts/{attempt_id}/questions/{order}/upload-url",
        json={"content_type": content_type, "size_bytes": len(body)},
    )
    assert response.status_code == 200, response.text
    ticket = response.json()
    key = urlparse(ticket["upload_url"]).path.lstrip("/")
    s3.put_object(Bucket="test-videos-bucket", Key=key, Body=body, ContentType=content_type)
    return client.post(f"/attempts/{attempt_id}/questions/{order}/recordings/{ticket['recording_id']}/complete")


def make_worker_context(db, transcriber=None, scorer=None):
    settings = get_settings()
    return WorkerContext(
        db=db,
        storage=VideoStorage(settings),
        transcriber=transcriber or FakeTranscriber(),
        scorer=scorer or FakeScorer(),
        settings=settings,
    )


def run_worker(ctx):
    """Do the worker's job until the queue is empty. Returns how many jobs it finished."""
    queue = JobQueue(ctx.settings)
    finished = 0
    while jobs := queue.receive_jobs(visibility_timeout=0, wait_seconds=0):
        for job in jobs:
            assert handle_job(job, ctx), f"job failed: {job.body}"
            queue.delete_job(job)  # like the real worker loop
            finished += 1
    return finished
