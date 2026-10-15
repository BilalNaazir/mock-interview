"""
Tests for the search agent's loop and guardrails.

Claude is replaced by ScriptedClaude, which plays back a fixed list of
moves ("call list_interviews", "call search_answers with these filters"...).
Everything else is real: the tools, the (pretend) vector search over the
test database, and the checks our code does on the agent's final answer.
"""

import json
import os
from types import SimpleNamespace

import pytest
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.search_agent import SearchAgent
from app.seed import seed_interviews
from tests.helpers import FakeEmbedder, InMemoryAnswerSearch, make_shared_answer

LANGSMITH = "I traced every retrieval step of our RAG pipeline in LangSmith to see which documents were used."
DOCKER = "I would use a slim base image and run the container as a non-root user."


def tool_use(name, tool_input, call_id="call-1"):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=tool_input)


def text(value):
    return SimpleNamespace(type="text", text=value)


class ScriptedClaude:
    """Pretend AsyncAnthropic client: returns the next scripted response each time."""

    def __init__(self, moves):
        self.moves = list(moves)
        self.requests = []
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **request):
        # Save a COPY of the conversation so far (the list keeps growing later).
        self.requests.append({**request, "messages": list(request["messages"])})
        return SimpleNamespace(content=self.moves.pop(0))

    def tool_output(self, request_number):
        """What our tool sent back to Claude, as seen in a later request."""
        last_message = self.requests[request_number]["messages"][-1]
        return json.loads(last_message["content"][0]["content"])


@pytest.fixture
def anyio_backend():
    return "asyncio"  # run the async tests with Python's standard asyncio


@pytest.fixture
async def async_db():
    client = AsyncMongoClient(os.environ["MONGODB_URI"])
    db = client["mock_interview_test"]
    await seed_interviews(db)  # list_interviews needs the interviews to exist
    yield db
    await client.close()


def make_agent(async_db, moves, settings=None):
    claude = ScriptedClaude(moves)
    settings = settings or get_settings()
    search = InMemoryAnswerSearch(async_db, settings)
    agent = SearchAgent(async_db, search, FakeEmbedder(), settings, client=claude)
    return agent, claude, search


@pytest.mark.anyio
async def test_the_agent_decomposes_the_question_and_finds_the_answer(async_db, db):
    langsmith_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    make_shared_answer(db, "devops-docker", 3, DOCKER)

    agent, claude, search = make_agent(async_db, [
        [tool_use("list_interviews", {})],
        [tool_use("search_answers", {"query": "observing a RAG pipeline with LangSmith",
                                     "interview_slug": "agentic-ai", "question_order": 3})],
        [tool_use("submit_answer", {"answer": "One answer mentions LangSmith.", "answer_ids": [langsmith_id]})],
    ])
    result = await agent.run("Which answer for question 3 talked about observing a RAG pipeline using LangSmith?")

    assert result["reply"] == "One answer mentions LangSmith."
    assert [str(a["_id"]) for a in result["answers"]] == [langsmith_id]
    # The precise part became filters...
    assert search.calls == [{"interview_slug": "agentic-ai", "question_order": 3}]
    # ...and the interview list Claude saw never included the private rubrics.
    interviews_seen = claude.tool_output(1)
    assert "key_points" not in json.dumps(interviews_seen)


@pytest.mark.anyio
async def test_search_results_rank_by_meaning(async_db, db):
    make_shared_answer(db, "devops-docker", 3, DOCKER)
    langsmith_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)

    agent, claude, _ = make_agent(async_db, [
        [tool_use("search_answers", {"query": "LangSmith RAG pipeline"})],
        [tool_use("submit_answer", {"answer": "done", "answer_ids": []})],
    ])
    await agent.run("LangSmith?")

    results = claude.tool_output(1)
    assert results[0]["answer_id"] == langsmith_id  # most relevant first
    assert results[0]["relevance"] > results[1]["relevance"]
    assert "LangSmith" in results[0]["excerpt"]


@pytest.mark.anyio
async def test_private_answers_are_never_found(async_db, db):
    make_shared_answer(db, "agentic-ai", 3, LANGSMITH, visibility="private")

    agent, claude, _ = make_agent(async_db, [
        [tool_use("search_answers", {"query": "LangSmith"})],
        [tool_use("submit_answer", {"answer": "nothing", "answer_ids": []})],
    ])
    await agent.run("LangSmith?")
    assert claude.tool_output(1) == []


@pytest.mark.anyio
async def test_made_up_answer_ids_are_thrown_away(async_db, db):
    real_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    never_found = make_shared_answer(db, "devops-docker", 1, DOCKER)

    agent, _, _ = make_agent(async_db, [
        [tool_use("search_answers", {"query": "LangSmith", "interview_slug": "agentic-ai"})],
        # The agent cites one real result, one it never saw, and one invented ID.
        [tool_use("submit_answer", {"answer": "x", "answer_ids": [real_id, never_found, "invented", real_id]})],
    ])
    result = await agent.run("LangSmith?")
    assert [str(a["_id"]) for a in result["answers"]] == [real_id]


@pytest.mark.anyio
async def test_the_agent_stops_after_the_step_limit(async_db, db):
    make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    settings = get_settings().model_copy(update={"search_agent_max_steps": 3})
    # A confused agent that keeps searching and never submits.
    moves = [[tool_use("search_answers", {"query": "LangSmith"}, call_id=f"c{i}")] for i in range(10)]

    agent, claude, _ = make_agent(async_db, moves, settings)
    result = await agent.run("LangSmith?")

    assert len(claude.requests) == 3
    assert result["reply"].startswith("I couldn't finish")
    assert len(result["answers"]) == 1  # it still returns what it found


@pytest.mark.anyio
async def test_a_plain_text_reply_still_finishes(async_db):
    agent, _, _ = make_agent(async_db, [[text("I'm not sure what you mean.")]])
    result = await agent.run("hmm")
    assert result == {"reply": "I'm not sure what you mean.", "answers": []}


@pytest.mark.anyio
async def test_bad_filters_are_ignored_not_passed_on(async_db, db):
    agent, _, search = make_agent(async_db, [
        [tool_use("search_answers", {"query": "x", "question_order": 99, "question_type": "anything"})],
        [tool_use("submit_answer", {"answer": "done", "answer_ids": []})],
    ])
    await agent.run("x")
    assert search.calls == [{}]
