"""
live.py - Live updates over a WebSocket.

When a candidate is looking at their answers, the browser opens a WebSocket
here. Whenever the worker moves an answer along (queued -> transcribing ->
scoring -> done), we push a short message, and the page fetches fresh data.

HOW WE NOTICE CHANGES: the worker is a separate program, so it can't talk to
the WebSocket connections held by this API. Instead, each connection checks
MongoDB every couple of seconds and only sends a message when something
changed. Remember the rule from the WebSocket demo: the DATABASE is the
source of truth, and the WebSocket is just the doorbell.

This also works with many copies of the API behind a load balancer, since
every copy reads the same database. At much bigger scale, you'd swap the
checking for MongoDB "change streams" or Redis pub/sub, so the database
announces changes instead of being asked - but the browser side would stay
exactly the same.

SECURITY - two things HTTP endpoints get for free that WebSockets don't:
  1. Login: browsers can't add an Authorization header to a WebSocket. So
     the browser sends its access token as the FIRST MESSAGE, and we close
     the connection if it doesn't arrive quickly or isn't valid. (Putting the
     token in the URL would also work, but URLs end up in server logs.)
  2. CORS doesn't apply to WebSockets, so any website could try to connect.
     We check the Origin header ourselves.
"""

import asyncio
import logging

import jwt
from bson import ObjectId
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pymongo.asynchronous.database import AsyncDatabase

from app.auth import TokenVerifier, get_token_verifier
from app.config import Settings, get_settings

router = APIRouter(tags=["live"])
logger = logging.getLogger("mock_interview.live")

# 1008 is the WebSocket close code for "policy violation" - used here for
# "not allowed": wrong website, no login, or not your attempt.
POLICY_VIOLATION = status.WS_1008_POLICY_VIOLATION


def get_websocket_db(websocket: WebSocket) -> AsyncDatabase:
    return websocket.app.state.db


async def processing_snapshot(db: AsyncDatabase, attempt_id: ObjectId) -> dict[str, str | None]:
    """A small summary of where each answer is: {"1": "done", "2": "transcribing", ...}"""
    answers = await db.answers.find(
        {"attempt_id": attempt_id, "status": "answered"}, {"question_order": 1, "processing.status": 1}
    ).to_list()
    return {str(a["question_order"]): a.get("processing", {}).get("status") for a in answers}


@router.websocket("/ws/attempts/{attempt_id}")
async def attempt_updates(
    websocket: WebSocket,
    attempt_id: str,
    db: AsyncDatabase = Depends(get_websocket_db),
    verifier: TokenVerifier = Depends(get_token_verifier),
    settings: Settings = Depends(get_settings),
):
    # --- Check 1: is this connection coming from our own website? ----------
    if websocket.headers.get("origin") not in settings.cors_origin_list:
        await websocket.close(code=POLICY_VIOLATION)
        return

    await websocket.accept()

    # --- Check 2: who is this? (the first message must be the login token) --
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=settings.ws_auth_timeout_seconds)
        if first.get("type") != "auth" or not isinstance(first.get("token"), str):
            raise ValueError("First message must be {type: 'auth', token: ...}")
        claims = await run_in_threadpool(verifier.verify, first["token"])
    except WebSocketDisconnect:
        return
    except (TimeoutError, ValueError, jwt.PyJWTError):
        await websocket.close(code=POLICY_VIOLATION, reason="Not logged in")
        return

    # --- Check 3: is this THEIR attempt? (same rule as the HTTP endpoints) --
    if not ObjectId.is_valid(attempt_id) or not await db.attempts.find_one(
        {"_id": ObjectId(attempt_id), "user_sub": claims["sub"]}
    ):
        await websocket.close(code=POLICY_VIOLATION, reason="Interview attempt not found")
        return

    # --- Watch for changes and ring the doorbell -----------------------------
    attempt_object_id = ObjectId(attempt_id)
    last_snapshot = None
    try:
        while True:
            snapshot = await processing_snapshot(db, attempt_object_id)
            if snapshot != last_snapshot:
                await websocket.send_json({"type": "processing_update", "answers": snapshot})
                last_snapshot = snapshot

            # Wait for the next check. Listening for a message (rather than just
            # sleeping) means we notice straight away if the browser disconnects.
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=settings.ws_poll_interval_seconds)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except TimeoutError:
                pass  # no message - normal; time for the next check
    except WebSocketDisconnect:
        pass  # the user closed the tab or navigated away - nothing to clean up
