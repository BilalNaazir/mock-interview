"""Tests for the interview endpoints."""


def test_anyone_can_list_the_five_interviews(client):
    response = client.get("/interviews")
    assert response.status_code == 200

    interviews = response.json()
    assert len(interviews) == 5
    assert {i["slug"] for i in interviews} == {
        "backend-python", "backend-node", "frontend-react", "agentic-ai", "devops-docker",
    }
    assert all(i["question_count"] == 5 for i in interviews)


def test_interview_detail_requires_login(client):
    response = client.get("/interviews/backend-python")
    assert response.status_code == 401


def test_each_interview_has_3_knowledge_then_2_situational(logged_in_client):
    for slug in ["backend-python", "backend-node", "frontend-react", "agentic-ai", "devops-docker"]:
        questions = logged_in_client.get(f"/interviews/{slug}").json()["questions"]
        types = [q["type"] for q in sorted(questions, key=lambda q: q["order"])]
        assert types == ["knowledge"] * 3 + ["situational"] * 2, slug


def test_rubric_is_never_sent_to_the_browser(logged_in_client):
    questions = logged_in_client.get("/interviews/agentic-ai").json()["questions"]
    assert all("key_points" not in q for q in questions)


def test_unknown_interview_returns_404(logged_in_client):
    response = logged_in_client.get("/interviews/does-not-exist")
    assert response.status_code == 404


def test_seeding_twice_does_not_create_duplicates(client):
    # Starting a second app runs the seed again; there should still be 5.
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as second:
        assert len(second.get("/interviews").json()) == 5
