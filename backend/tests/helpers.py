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


# ---------------------------------------------------------------------------
# Phase 5: pretend embeddings and a pretend vector search
# ---------------------------------------------------------------------------

import math  # noqa: E402
import re  # noqa: E402
import zlib  # noqa: E402

from app.vector_search import FILTER_FIELDS, AnswerSearch  # noqa: E402

DIMENSIONS = 1024


def word_vector(text: str) -> list[float]:
    """
    A pretend embedding: each word adds 1 to one of 1024 slots (chosen by a
    checksum of the word), then the list is scaled to length 1. Texts that
    share words get similar vectors - a crude stand-in for real meaning.
    """
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"[a-z]+", text.lower()):
        vector[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
    length = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / length for v in vector]


class FakeEmbedder:
    """Pretend Voyage: both the worker's method and the API's method."""

    def __init__(self, fail=False):
        self.fail = fail
        self.documents = []
        self.queries = []

    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("Voyage is down")
        self.documents.extend(texts)
        return [word_vector(text) for text in texts]

    async def embed_query(self, text):
        self.queries.append(text)
        return word_vector(text)


class InMemoryAnswerSearch(AnswerSearch):
    """
    Pretend MongoDB vector search: loads the matching answers and ranks them
    in Python. It applies the same rules as the real pipeline - shared only,
    and only the allowed filter fields.
    """

    def __init__(self, db, settings):
        super().__init__(db, settings, available=True)
        self.calls = []

    async def search(self, query_vector, filters, limit=5):
        self.calls.append(filters)
        query = {"visibility": "shared", "embedding": {"$exists": True}}
        query.update({k: v for k, v in filters.items() if k in FILTER_FIELDS and v is not None})
        answers = await self.db.answers.find(query).to_list()
        for answer in answers:
            # Cosine similarity: both vectors have length 1, so it's the dot product.
            answer["search_score"] = sum(a * b for a, b in zip(query_vector, answer.pop("embedding"), strict=True))
        answers.sort(key=lambda a: a["search_score"], reverse=True)
        return answers[:limit]


def make_shared_answer(
    db, interview_slug, question_order, transcript, visibility="shared", user_sub="someone-else-456"
):
    """Put a finished, embedded answer straight into the test database."""
    from bson import ObjectId

    from app.embeddings import build_answer_text

    interview = db.interviews.find_one({"slug": interview_slug})
    question = next(q for q in interview["questions"] if q["order"] == question_order)
    answer = {
        "attempt_id": ObjectId(),
        "user_sub": user_sub,
        "interview_slug": interview_slug,
        "question_order": question_order,
        "question_type": question["type"],
        "question_text": question["text"],
        "status": "answered",
        "visibility": visibility,
        "recordings": [{"recording_id": "r1", "kind": "main", "status": "uploaded", "transcript": transcript,
                        "video_key": "videos/secret/key.webm"}],
        "follow_ups": [],
        "evaluation": {"kind": "knowledge", "score": 80, "covered_points": [], "missing_points": [],
                       "feedback": "Nice."},
    }
    answer["search_text"] = build_answer_text(answer)
    answer["embedding"] = word_vector(answer["search_text"])
    return str(db.answers.insert_one(answer).inserted_id)
