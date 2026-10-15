"""
embeddings.py - Turning text into embeddings with Voyage AI.

An EMBEDDING is a long list of numbers (1024 here) that captures what a piece
of text MEANS. Texts with similar meanings get similar lists of numbers, even
when they use different words. That's what lets a search for "monitoring a
RAG pipeline" find an answer about "tracing retrieval steps in LangSmith".

Two kinds of text get embedded:
  - DOCUMENTS: each finished answer (done by the worker, in processing.py)
  - QUERIES:   each search (done by the API's search agent, in search_agent.py)
Voyage is told which is which (input_type), because it embeds them slightly
differently to make searching more accurate.
"""

from typing import Protocol

import httpx

from app.config import Settings

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


def build_answer_text(answer: dict) -> str:
    """
    The text that represents one answer in search: the question, the main
    transcript, and any follow-up questions with their transcripts. The
    follow-ups matter - the detail someone searches for is often in there.
    """
    transcripts = {r["recording_id"]: r.get("transcript") or "" for r in answer["recordings"]}
    main = next((r for r in answer["recordings"] if r["kind"] == "main"), {})
    parts = [f"Question: {answer['question_text']}", f"Answer: {main.get('transcript') or ''}"]
    for follow_up in sorted(answer.get("follow_ups", []), key=lambda f: f["number"]):
        if follow_up.get("recording_id"):
            parts.append(f"Follow-up question: {follow_up['question']}")
            parts.append(f"Answer: {transcripts.get(follow_up['recording_id'], '')}")
    return "\n".join(parts)


class DocumentEmbedder(Protocol):
    """What the worker needs. Tests use a fake with this same method."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class QueryEmbedder(Protocol):
    """What the API needs. Tests use a fake with this same method."""

    async def embed_query(self, text: str) -> list[float]: ...


class VoyageEmbedder:
    """
    Calls Voyage AI's embeddings endpoint over HTTP. We use httpx (already
    installed) instead of Voyage's own library, so you can see exactly what's
    sent and received - it's one ordinary POST request.
    """

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None):
        # `transport` is only ever set by tests: it swaps the real network for
        # a pretend one, so tests can check exactly what we'd send to Voyage.
        self.transport = transport
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        # .get_secret_value() is the only way to read a SecretStr. Doing it
        # here, in one place, makes it easy to see where the key is used.
        self.headers = {"Authorization": f"Bearer {settings.voyage_api_key.get_secret_value()}"}

    def _body(self, texts: list[str], input_type: str) -> dict:
        return {
            "input": texts,
            "model": self.model,
            "input_type": input_type,        # "document" or "query"
            "output_dimension": self.dimensions,
        }

    @staticmethod
    def _vectors(response: httpx.Response) -> list[list[float]]:
        # raise_for_status() turns an error reply (like 401 for a wrong key)
        # into a Python exception, instead of failing later in a confusing way.
        response.raise_for_status()
        # Voyage replies {"data": [{"embedding": [...], "index": 0}, ...]}.
        # Sorting by "index" guarantees the order matches the texts we sent.
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Ordinary (blocking) version, for the worker."""
        with httpx.Client(timeout=30, transport=self.transport) as client:
            response = client.post(VOYAGE_URL, headers=self.headers, json=self._body(texts, "document"))
        return self._vectors(response)

    async def embed_query(self, text: str) -> list[float]:
        """Async version, for the API, so the server stays responsive while waiting."""
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(VOYAGE_URL, headers=self.headers, json=self._body([text], "query"))
        return self._vectors(response)[0]
