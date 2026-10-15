"""
Tests for the Community endpoints: browsing, viewing and searching shared answers.
Answers are put straight into the database with make_shared_answer().
"""

import json

from app.routers.community import get_search_agent
from tests.helpers import make_shared_answer

LANGSMITH = "I traced every retrieval step of our RAG pipeline in LangSmith to see which documents were used."
DOCKER = "I would use a slim base image and run the container as a non-root user."


def test_only_shared_answers_are_listed(logged_in_client, db):
    shared = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    make_shared_answer(db, "agentic-ai", 3, "a private answer", visibility="private")

    answers = logged_in_client.get("/community/answers").json()
    assert [a["answer_id"] for a in answers] == [shared]


def test_answers_can_be_filtered_by_interview_and_question(logged_in_client, db):
    wanted = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    make_shared_answer(db, "agentic-ai", 1, "about workflows")
    make_shared_answer(db, "devops-docker", 3, DOCKER)

    answers = logged_in_client.get("/community/answers", params={"interview_slug": "agentic-ai", "question_order": 3})
    assert [a["answer_id"] for a in answers.json()] == [wanted]


def test_shared_answers_never_reveal_who_gave_them(logged_in_client, db):
    answer_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    detail = logged_in_client.get(f"/community/answers/{answer_id}").json()

    text = json.dumps(detail)
    assert "someone-else-456" not in text  # the owner's user ID
    assert "videos/secret/key.webm" not in text  # the video's location
    assert "embedding" not in detail
    assert detail["transcript"] == LANGSMITH
    assert detail["is_mine"] is False


def test_your_own_shared_answers_are_marked_as_yours(logged_in_client, db):
    answer_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH, user_sub="test-user-123")
    assert logged_in_client.get(f"/community/answers/{answer_id}").json()["is_mine"] is True


def test_a_private_answer_looks_exactly_like_a_missing_one(logged_in_client, db):
    private = make_shared_answer(db, "agentic-ai", 3, LANGSMITH, visibility="private")
    assert logged_in_client.get(f"/community/answers/{private}").status_code == 404
    assert logged_in_client.get("/community/answers/0123456789abcdef01234567").status_code == 404
    assert logged_in_client.get("/community/answers/not-an-id").status_code == 404


def test_community_pages_need_login(client):
    assert client.get("/community/answers").status_code == 401


# ---------------------------------------------------------------------------
# The search endpoint (the agent itself is tested in test_search_agent.py)
# ---------------------------------------------------------------------------

class StubAgent:
    """Stands in for the search agent: returns whichever answers it was given."""

    def __init__(self, answers):
        self.answers = answers
        self.questions = []

    async def run(self, question):
        self.questions.append(question)
        return {"reply": "Here's what I found.", "answers": self.answers}


def test_search_returns_the_agents_reply_and_answers(logged_in_client, db):
    answer_id = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    agent = StubAgent([db.answers.find_one({})])
    logged_in_client.app.dependency_overrides[get_search_agent] = lambda: agent

    response = logged_in_client.post("/community/search", json={"question": "Who used LangSmith?"})
    assert response.json()["reply"] == "Here's what I found."
    assert [a["answer_id"] for a in response.json()["answers"]] == [answer_id]
    assert agent.questions == ["Who used LangSmith?"]


def test_search_is_unavailable_when_switched_off(logged_in_client):
    logged_in_client.app.dependency_overrides[get_search_agent] = lambda: None
    response = logged_in_client.post("/community/search", json={"question": "anything"})
    assert response.status_code == 503


def test_searches_are_limited_per_hour(logged_in_client):
    from app.config import get_settings

    logged_in_client.app.dependency_overrides[get_search_agent] = lambda: StubAgent([])
    logged_in_client.app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"searches_per_hour": 2}
    )

    codes = [logged_in_client.post("/community/search", json={"question": "testing"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_empty_questions_are_rejected(logged_in_client):
    logged_in_client.app.dependency_overrides[get_search_agent] = lambda: StubAgent([])
    assert logged_in_client.post("/community/search", json={"question": ""}).status_code == 422
