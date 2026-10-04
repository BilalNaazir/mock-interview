"""
Tests for the live-updates WebSocket.
"""

import os

import pytest
from fastapi import WebSocketDisconnect
from pymongo import MongoClient

from app.auth import get_token_verifier

GOOD_ORIGIN = {"origin": "http://localhost:5173"}


class FakeVerifier:
    """Pretends every token belongs to this user (real checks are in test_auth.py)."""

    def __init__(self, sub):
        self.sub = sub

    def verify(self, token):
        if token != "valid-token":
            import jwt

            raise jwt.InvalidTokenError("bad token")
        return {"sub": self.sub}


@pytest.fixture
def attempt_id(logged_in_client):
    logged_in_client.app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier("test-user-123")
    return logged_in_client.post(
        "/attempts", json={"interview_slug": "backend-python", "consent_to_recording": True}
    ).json()["attempt_id"]


def test_connections_from_other_websites_are_refused(logged_in_client, attempt_id):
    with pytest.raises(WebSocketDisconnect):
        with logged_in_client.websocket_connect(f"/ws/attempts/{attempt_id}", headers={"origin": "https://evil.example"}):
            pass


def test_the_connection_closes_if_no_login_arrives(logged_in_client, attempt_id):
    with logged_in_client.websocket_connect(f"/ws/attempts/{attempt_id}", headers=GOOD_ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()  # we never sent the token, so the server gives up
        assert closed.value.code == 1008


def test_a_bad_token_is_refused(logged_in_client, attempt_id):
    with logged_in_client.websocket_connect(f"/ws/attempts/{attempt_id}", headers=GOOD_ORIGIN) as ws:
        ws.send_json({"type": "auth", "token": "forged"})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_you_cannot_watch_someone_elses_attempt(logged_in_client, attempt_id):
    logged_in_client.app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier("someone-else-456")
    with logged_in_client.websocket_connect(f"/ws/attempts/{attempt_id}", headers=GOOD_ORIGIN) as ws:
        ws.send_json({"type": "auth", "token": "valid-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008


def test_status_changes_are_pushed_to_the_browser(logged_in_client, attempt_id):
    from bson import ObjectId

    db = MongoClient(os.environ["MONGODB_URI"])["mock_interview_test"]
    db.answers.insert_one(
        {
            "attempt_id": ObjectId(attempt_id),
            "question_order": 1,
            "status": "answered",
            "processing": {"status": "queued"},
        }
    )

    with logged_in_client.websocket_connect(f"/ws/attempts/{attempt_id}", headers=GOOD_ORIGIN) as ws:
        ws.send_json({"type": "auth", "token": "valid-token"})
        assert ws.receive_json() == {"type": "processing_update", "answers": {"1": "queued"}}

        # The worker moves the answer along...
        db.answers.update_one({"attempt_id": ObjectId(attempt_id)}, {"$set": {"processing.status": "transcribing"}})
        # ...and the browser hears about it without asking.
        assert ws.receive_json() == {"type": "processing_update", "answers": {"1": "transcribing"}}

        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
