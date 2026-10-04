"""
attempts.py - Taking an interview.

The flow for each question:
  1. POST .../upload-url   -> "I recorded my answer, where do I put it?"
                              We check everything, then hand back a presigned URL.
  2. (the browser uploads the video straight to S3 - not through us)
  3. POST .../complete     -> "Upload finished."
                              We check S3 really has the file, mark the question
                              answered, and move on to the next question.

AUTHORIZATION RULE used in every endpoint: you can only see or change YOUR OWN
attempts. Every database lookup includes the logged-in user's ID, so changing
an ID in the URL can never reveal someone else's interview. If an attempt
doesn't exist OR belongs to someone else, we answer 404 either way, so the
response doesn't even reveal that it exists.
"""

import uuid
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pymongo.asynchronous.database import AsyncDatabase

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    AttemptDetail,
    AttemptSummary,
    CompleteRecordingResponse,
    StartAttemptRequest,
    StartAttemptResponse,
    UploadUrlRequest,
    UploadUrlResponse,
    VideoUrlResponse,
)
from app.storage import VideoStorage, get_storage

router = APIRouter(prefix="/attempts", tags=["attempts"])

# The video formats we accept, and the file extension for each. Chrome, Edge
# and Firefox record WebM; Safari records MP4.
ALLOWED_CONTENT_TYPES = {"video/webm": "webm", "video/mp4": "mp4"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview attempt not found")


async def load_own_attempt(db: AsyncDatabase, attempt_id: str, user: dict) -> dict:
    """Fetch an attempt, but ONLY if it belongs to the logged-in user."""
    # MongoDB IDs have a fixed format; anything else can't be a real attempt.
    if not ObjectId.is_valid(attempt_id):
        raise not_found()
    attempt = await db.attempts.find_one({"_id": ObjectId(attempt_id), "user_sub": user["cognito_sub"]})
    if attempt is None:
        raise not_found()
    return attempt


async def load_interview(db: AsyncDatabase, slug: str) -> dict:
    interview = await db.interviews.find_one({"slug": slug})
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def require_storage(storage: VideoStorage) -> None:
    if not storage.is_configured:
        # 503 = "service unavailable": the server isn't set up for this yet.
        raise HTTPException(status_code=503, detail="Video storage isn't configured (S3_VIDEOS_BUCKET is empty)")


async def build_attempt_detail(db: AsyncDatabase, attempt: dict, settings: Settings) -> dict:
    interview = await load_interview(db, attempt["interview_slug"])
    answered = await db.answers.find(
        {"attempt_id": attempt["_id"], "status": "answered"}, {"question_order": 1}
    ).to_list()
    answered_orders = {a["question_order"] for a in answered}

    return {
        "attempt_id": str(attempt["_id"]),
        "interview_slug": interview["slug"],
        "interview_title": interview["title"],
        "status": attempt["status"],
        "current_question": attempt["current_question"],
        "questions": [
            {"order": q["order"], "type": q["type"], "text": q["text"], "answered": q["order"] in answered_orders}
            for q in sorted(interview["questions"], key=lambda q: q["order"])
        ],
        "limits": {
            "max_recording_seconds": settings.max_recording_seconds,
            "max_upload_bytes": settings.max_upload_bytes,
            "allowed_content_types": list(ALLOWED_CONTENT_TYPES),
        },
    }


# ---------------------------------------------------------------------------
# Starting and viewing attempts
# ---------------------------------------------------------------------------

@router.post("", response_model=StartAttemptResponse, status_code=status.HTTP_201_CREATED)
async def start_attempt(
    body: StartAttemptRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    interview = await load_interview(db, body.interview_slug)

    if not body.consent_to_recording:
        raise HTTPException(status_code=400, detail="You must agree to being recorded to take an interview")

    # If they already have an unfinished attempt at this interview, carry on
    # with it instead of creating a new one (e.g. they closed the tab halfway).
    existing = await db.attempts.find_one(
        {"user_sub": user["cognito_sub"], "interview_slug": interview["slug"], "status": "in_progress"}
    )
    if existing is not None:
        return {"attempt_id": str(existing["_id"]), "resumed": True}

    now = datetime.now(UTC)
    result = await db.attempts.insert_one(
        {
            "user_sub": user["cognito_sub"],
            "interview_slug": interview["slug"],
            "status": "in_progress",
            "current_question": 1,
            "question_count": len(interview["questions"]),
            "consented_to_recording_at": now,  # a record of WHEN they agreed (privacy law)
            "started_at": now,
            "completed_at": None,
        }
    )
    return {"attempt_id": str(result.inserted_id), "resumed": False}


@router.get("", response_model=list[AttemptSummary])
async def list_my_attempts(
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    attempts = await db.attempts.find({"user_sub": user["cognito_sub"]}).sort("started_at", -1).to_list()
    titles = {i["slug"]: i["title"] for i in await db.interviews.find({}, {"slug": 1, "title": 1}).to_list()}

    summaries = []
    for attempt in attempts:
        answered_count = await db.answers.count_documents({"attempt_id": attempt["_id"], "status": "answered"})
        summaries.append(
            {
                "attempt_id": str(attempt["_id"]),
                "interview_slug": attempt["interview_slug"],
                "interview_title": titles.get(attempt["interview_slug"], attempt["interview_slug"]),
                "status": attempt["status"],
                "answered_count": answered_count,
                "question_count": attempt["question_count"],
                "started_at": attempt["started_at"],
            }
        )
    return summaries


@router.get("/{attempt_id}", response_model=AttemptDetail)
async def get_attempt(
    attempt_id: str,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    attempt = await load_own_attempt(db, attempt_id, user)
    return await build_attempt_detail(db, attempt, settings)


# ---------------------------------------------------------------------------
# Uploading an answer
# ---------------------------------------------------------------------------

@router.post("/{attempt_id}/questions/{order}/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(
    attempt_id: str,
    order: int,
    body: UploadUrlRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    storage: VideoStorage = Depends(get_storage),
):
    require_storage(storage)
    attempt = await load_own_attempt(db, attempt_id, user)

    # 409 = "conflict": the request makes sense, but not in the current state.
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=409, detail="This interview is already finished")
    if order != attempt["current_question"]:
        raise HTTPException(status_code=409, detail=f"Please answer question {attempt['current_question']} next")

    # Browsers sometimes add details like "video/webm;codecs=vp9". We only
    # need the main type, so we keep the part before the ";".
    content_type = body.content_type.split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported video format: {content_type}")
    if body.size_bytes > settings.max_upload_bytes:
        # 413 = "content too large"
        raise HTTPException(status_code=413, detail=f"Recording is larger than {settings.max_upload_mb} MB")

    interview = await load_interview(db, attempt["interview_slug"])
    question = next(q for q in interview["questions"] if q["order"] == order)

    existing_answer = await db.answers.find_one({"attempt_id": attempt["_id"], "question_order": order})
    if existing_answer is not None and existing_answer["status"] == "answered":
        raise HTTPException(status_code=409, detail="This question has already been answered")

    recording_id = uuid.uuid4().hex  # a random, unguessable ID
    # Where the file will live in the bucket. Grouping by user and attempt
    # makes it easy to find (or delete) everything belonging to one person.
    video_key = (
        f"videos/{user['cognito_sub']}/{attempt_id}/"
        f"q{order}-{recording_id}.{ALLOWED_CONTENT_TYPES[content_type]}"
    )
    now = datetime.now(UTC)
    recording = {
        "recording_id": recording_id,
        "kind": "main",  # Phase 4 adds "follow_up" recordings for situational questions
        "video_key": video_key,
        "content_type": content_type,
        "size_bytes": body.size_bytes,
        "status": "awaiting_upload",
        "created_at": now,
        "uploaded_at": None,
    }

    # One answer document per question. "Upsert" creates it on the first
    # try; if the user retries (say, the upload failed), the unfinished
    # recording is simply replaced by the new one.
    await db.answers.update_one(
        {"attempt_id": attempt["_id"], "question_order": order},
        {
            "$setOnInsert": {
                "attempt_id": attempt["_id"],
                "user_sub": user["cognito_sub"],
                "interview_slug": attempt["interview_slug"],
                "question_order": order,
                "question_type": question["type"],
                # A copy of the question text, so the answer still makes sense
                # even if the question is reworded later.
                "question_text": question["text"],
                "status": "recording",
                "visibility": "private",  # nobody else can see it (sharing comes in Phase 5)
                "created_at": now,
            },
            "$set": {"recordings": [recording]},
        },
        upsert=True,
    )

    # generate_presigned_url doesn't contact AWS - it just does maths with
    # your keys - but it's ordinary blocking code, so we run it in a thread.
    upload_url = await run_in_threadpool(storage.presign_upload, video_key, content_type, body.size_bytes)
    return {
        "recording_id": recording_id,
        "upload_url": upload_url,
        # The browser must send this header exactly, or S3 rejects the upload.
        # (It sends Content-Length by itself; browsers don't let code set it.)
        "upload_headers": {"Content-Type": content_type},
        "expires_in_seconds": settings.upload_url_expiry_seconds,
    }


@router.post(
    "/{attempt_id}/questions/{order}/recordings/{recording_id}/complete",
    response_model=CompleteRecordingResponse,
)
async def complete_recording(
    attempt_id: str,
    order: int,
    recording_id: str,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    storage: VideoStorage = Depends(get_storage),
):
    require_storage(storage)
    attempt = await load_own_attempt(db, attempt_id, user)

    answer = await db.answers.find_one(
        {"attempt_id": attempt["_id"], "question_order": order, "recordings.recording_id": recording_id}
    )
    if answer is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    recording = next(r for r in answer["recordings"] if r["recording_id"] == recording_id)

    # IDEMPOTENT: if this was already completed (say the user double-clicked,
    # or the browser retried), just report the current state - don't redo it.
    if recording["status"] == "uploaded":
        fresh = await db.attempts.find_one({"_id": attempt["_id"]})
        return {"status": fresh["status"], "current_question": fresh["current_question"]}

    # Never just trust the browser: check S3 actually has the file.
    info = await run_in_threadpool(storage.get_uploaded_file_info, recording["video_key"])
    if info is None:
        raise HTTPException(status_code=400, detail="The video hasn't finished uploading yet")

    # The presigned URL already forces the right size and type, so this
    # should never fail - but checking twice costs nothing ("defence in depth").
    if info.size_bytes != recording["size_bytes"] or info.content_type != recording["content_type"]:
        await run_in_threadpool(storage.delete, recording["video_key"])
        raise HTTPException(status_code=400, detail="The uploaded file doesn't match what was expected")

    now = datetime.now(UTC)
    # Build the updated list of recordings in Python: the same list, with
    # this one recording marked as uploaded. Then save the whole list.
    updated_recordings = [
        {**r, "status": "uploaded", "uploaded_at": now} if r["recording_id"] == recording_id else r
        for r in answer["recordings"]
    ]
    await db.answers.update_one(
        # Only update if the answer is still being recorded. If two requests
        # race each other, the second one finds nothing to update.
        {"_id": answer["_id"], "status": "recording"},
        {"$set": {"recordings": updated_recordings, "status": "answered", "answered_at": now}},
    )

    # Move on to the next question. Including current_question in the filter
    # means two simultaneous requests can't BOTH move it forward.
    next_question = order + 1
    finished = next_question > attempt["question_count"]
    await db.attempts.update_one(
        {"_id": attempt["_id"], "current_question": order},
        {
            "$set": {
                "current_question": next_question,
                "status": "completed" if finished else "in_progress",
                "completed_at": now if finished else None,
            }
        },
    )

    # Phase 3: this is where a job goes onto the SQS queue for transcription.
    # Phase 4: for situational questions, the STAR check decides whether to
    #          ask a follow-up instead of moving to the next question.

    fresh = await db.attempts.find_one({"_id": attempt["_id"]})
    return {"status": fresh["status"], "current_question": fresh["current_question"]}


# ---------------------------------------------------------------------------
# Watching an answer back
# ---------------------------------------------------------------------------

@router.get("/{attempt_id}/questions/{order}/video-url", response_model=VideoUrlResponse)
async def get_video_url(
    attempt_id: str,
    order: int,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    storage: VideoStorage = Depends(get_storage),
):
    require_storage(storage)
    attempt = await load_own_attempt(db, attempt_id, user)  # <- the ownership check

    answer = await db.answers.find_one(
        {"attempt_id": attempt["_id"], "question_order": order, "status": "answered"}
    )
    if answer is None:
        raise HTTPException(status_code=404, detail="No answer recorded for this question")

    recording = next(r for r in answer["recordings"] if r["kind"] == "main" and r["status"] == "uploaded")
    url = await run_in_threadpool(storage.presign_download, recording["video_key"])
    return {
        "url": url,
        "content_type": recording["content_type"],
        "expires_in_seconds": settings.video_url_expiry_seconds,
    }
