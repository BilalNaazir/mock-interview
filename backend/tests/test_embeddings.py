"""
Tests for embeddings (Voyage), the worker's embedding step, the backfill
script, and the vector search pipeline and index setup.
"""

import json

import httpx
import pytest
from pydantic import SecretStr
from pymongo.errors import OperationFailure

from app.backfill_embeddings import backfill
from app.config import get_settings
from app.embeddings import VOYAGE_URL, VoyageEmbedder, build_answer_text
from app.vector_search import build_search_pipeline, ensure_vector_index
from tests.helpers import (
    ALL_CLEAR,
    FakeEmbedder,
    FakeScorer,
    make_worker_context,
    run_worker,
    start_attempt,
    submit_recording,
)

# ---------------------------------------------------------------------------
# The text that gets embedded
# ---------------------------------------------------------------------------


def test_answer_text_includes_the_question_and_answered_follow_ups():
    answer = {
        "question_text": "Tell me about a time...",
        "recordings": [
            {"recording_id": "m", "kind": "main", "transcript": "We fixed a slow API."},
            {"recording_id": "f1", "kind": "follow_up", "transcript": "I added an index."},
        ],
        "follow_ups": [
            {"number": 1, "question": "What did you do?", "recording_id": "f1"},
            {"number": 2, "question": "Not answered yet", "recording_id": None},
        ],
    }
    assert build_answer_text(answer) == (
        "Question: Tell me about a time...\n"
        "Answer: We fixed a slow API.\n"
        "Follow-up question: What did you do?\n"
        "Answer: I added an index."
    )


# ---------------------------------------------------------------------------
# Calling Voyage (with a pretend network, so nothing is really sent)
# ---------------------------------------------------------------------------


def test_voyage_request_has_the_right_shape():
    sent = []

    def pretend_voyage(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        # Reply out of order, to check we sort by "index".
        return httpx.Response(200, json={"data": [{"embedding": [0.2], "index": 1}, {"embedding": [0.1], "index": 0}]})

    settings = get_settings().model_copy(update={"voyage_api_key": SecretStr("secret-key")})
    embedder = VoyageEmbedder(settings, transport=httpx.MockTransport(pretend_voyage))

    assert embedder.embed_documents(["first", "second"]) == [[0.1], [0.2]]

    [request] = sent
    assert str(request.url) == VOYAGE_URL
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert json.loads(request.content) == {
        "input": ["first", "second"],
        "model": "voyage-4-lite",
        "input_type": "document",
        "output_dimension": 1024,
    }


@pytest.mark.anyio
async def test_queries_are_embedded_as_queries():
    sent = []

    def pretend_voyage(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"embedding": [0.5], "index": 0}]})

    embedder = VoyageEmbedder(get_settings(), transport=httpx.MockTransport(pretend_voyage))
    assert await embedder.embed_query("LangSmith") == [0.5]
    assert sent[0]["input_type"] == "query"


def test_a_voyage_error_becomes_an_exception():
    embedder = VoyageEmbedder(get_settings(), transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(httpx.HTTPStatusError):
        embedder.embed_documents(["x"])


def test_the_key_is_hidden_when_settings_are_printed():
    settings = get_settings().model_copy(update={"voyage_api_key": SecretStr("secret-key")})
    assert "secret-key" not in repr(settings)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# The worker's embedding step
# ---------------------------------------------------------------------------


def test_finished_knowledge_answers_are_embedded(logged_in_client, s3, db):
    attempt_id = start_attempt(logged_in_client)
    submit_recording(logged_in_client, s3, attempt_id, 1)
    embedder = FakeEmbedder()
    worker = make_worker_context(db)
    worker.embedder = embedder

    run_worker(worker)

    answer = db.answers.find_one({"question_order": 1})
    assert len(answer["embedding"]) == 1024
    assert answer["search_text"].startswith("Question: ")
    assert embedder.documents == [answer["search_text"]]


def test_situational_answers_are_embedded_only_once_accepted(logged_in_client, s3, db):
    attempt_id = start_attempt(logged_in_client)
    missing_result = {"situation": "clear", "task": "clear", "action": "clear", "result": "missing"}
    worker = make_worker_context(db, scorer=FakeScorer(star_ratings=[missing_result, ALL_CLEAR]))
    worker.embedder = FakeEmbedder()
    for order in (1, 2, 3, 4):
        submit_recording(logged_in_client, s3, attempt_id, order)
        run_worker(worker)

    # A follow-up was asked, so question 4 isn't finished: no embedding yet.
    assert "embedding" not in db.answers.find_one({"question_order": 4})

    submit_recording(logged_in_client, s3, attempt_id, 4)  # answer the follow-up
    run_worker(worker)
    answer = db.answers.find_one({"question_order": 4})
    assert "embedding" in answer
    assert "Follow-up question:" in answer["search_text"]


def test_an_embedding_failure_does_not_fail_the_job(logged_in_client, s3, db):
    attempt_id = start_attempt(logged_in_client)
    submit_recording(logged_in_client, s3, attempt_id, 1)
    worker = make_worker_context(db)
    worker.embedder = FakeEmbedder(fail=True)

    run_worker(worker)  # run_worker checks every job succeeded

    answer = db.answers.find_one({"question_order": 1})
    assert answer["processing"]["status"] == "done"
    assert answer["evaluation"]["score"] == 75  # the candidate still gets their score
    assert "embedding" not in answer


def test_backfill_embeds_only_what_is_missing(logged_in_client, s3, db):
    attempt_id = start_attempt(logged_in_client)
    for order in (1, 2):
        submit_recording(logged_in_client, s3, attempt_id, order)
    run_worker(make_worker_context(db))  # no embedder, like before Phase 5

    settings = get_settings()
    assert backfill(db, FakeEmbedder(), settings) == 2
    assert backfill(db, FakeEmbedder(), settings) == 0  # safe to run again


# ---------------------------------------------------------------------------
# The vector search pipeline and index
# ---------------------------------------------------------------------------


def test_the_pipeline_always_filters_to_shared_answers():
    pipeline = build_search_pipeline(
        [0.1], {"question_order": 3, "interview_slug": None, "user_sub": "sneaky"}, 5, "answer_embeddings"
    )
    stage = pipeline[0]["$vectorSearch"]
    assert stage["filter"] == {"$and": [{"visibility": "shared"}, {"question_order": 3}]}
    assert stage["limit"] == 5 and stage["numCandidates"] == 100
    assert pipeline[1:] == [{"$set": {"search_score": {"$meta": "vectorSearchScore"}}}, {"$unset": "embedding"}]


class FakeCursor:
    def __init__(self, items):
        self.items = items

    async def to_list(self):
        return self.items


class FakeAnswers:
    def __init__(self, existing=(), unsupported=False):
        self.existing, self.unsupported, self.created = list(existing), unsupported, []

    async def list_search_indexes(self, name):
        if self.unsupported:
            raise OperationFailure("search indexes are not supported here")
        return FakeCursor(self.existing)

    async def create_search_index(self, model):
        self.created.append(model.document)


class FakeDb:
    def __init__(self, answers):
        self.answers = answers

    async def create_collection(self, name):
        pass


@pytest.mark.anyio
async def test_the_vector_index_is_created_when_missing():
    answers = FakeAnswers()
    assert await ensure_vector_index(FakeDb(answers), get_settings()) is True
    [index] = answers.created
    assert index["name"] == "answer_embeddings" and index["type"] == "vectorSearch"
    assert index["definition"]["fields"][0] == {
        "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine",
    }


@pytest.mark.anyio
async def test_an_existing_index_is_left_alone():
    answers = FakeAnswers(existing=[{"name": "answer_embeddings"}])
    assert await ensure_vector_index(FakeDb(answers), get_settings()) is True
    assert answers.created == []


@pytest.mark.anyio
async def test_without_vector_search_the_app_carries_on():
    assert await ensure_vector_index(FakeDb(FakeAnswers(unsupported=True)), get_settings()) is False
