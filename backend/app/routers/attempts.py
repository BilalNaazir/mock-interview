"""
attempts.py - Taking an interview.

The flow for each recording:
  1. POST .../upload-url   -> "I recorded my answer, where do I put it?"
                              We check everything, then hand back a presigned URL.
  2. (the browser uploads the video straight to S3 - not through us)
  3. POST .../complete     -> "Upload finished."
                              We check S3 really has the file, then:
                              - KNOWLEDGE question: mark it answered, queue it
                                for scoring, and move to the next question.
                              - SITUATIONAL question (Phase 4): queue it for STAR
                                evaluation and WAIT. The worker then either asks
                                a follow-up question (and the user records again)
                                or accepts the answer and moves the interview on.

The browser always just asks for an upload URL for the CURRENT question; the
backend works out whether that's the main answer or a follow-up answer.

AUTHORIZATION RULE used in every endpoint: you can only see or change YOUR OWN
attempts. Every database lookup includes the logged-in user's ID, so changing
an ID in the URL can never reveal someone else's interview. If an attempt
doesn't exist OR belongs to someone else, we answer 404 either way, so the
response doesn't even reveal that it exists.
"""

import logging
import uuid
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pymongo.asynchronous.database import AsyncDatabase

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.interview_flow import next_question_fields
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
from app.queue import JobQueue, get_queue
from app.storage import VideoStorage, get_storage

router = APIRouter(prefix="/attempts", tags=["attempts"])
logger = logging.getLogger("mock_interview.attempts")

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


def pending_follow_up(answer: dict) -> dict | None:
    """The follow-up question currently waiting for an answer, if there is one."""
    return next((f for f in answer.get("follow_ups", []) if f["status"] == "awaiting_answer"), None)


async def advance_attempt(db: AsyncDatabase, attempt: dict, order: int) -> None:
    """Move the interview on from question `order`."""
    await db.attempts.update_one(
        # Including current_question in the filter means two simultaneous
        # requests can't BOTH move it forward.
        {"_id": attempt["_id"], "current_question": order},
        {"$set": next_question_fields(order, attempt["question_count"], datetime.now(UTC))},
    )


async def build_attempt_detail(db: AsyncDatabase, attempt: dict, settings: Settings) -> dict:
    interview = await load_interview(db, attempt["interview_slug"])
    answers = await db.answers.find({"attempt_id": attempt["_id"]}).to_list()
    answers_by_order = {a["question_order"]: a for a in answers}

    def results_for(order: int) -> dict:
        """What the browser should know about one question's answer."""
        answer = answers_by_order.get(order)
        if answer is None:
            return {"answered": False}
        transcripts = {r["recording_id"]: r.get("transcript") for r in answer["recordings"]}
        main = next((r for r in answer["recordings"] if r["kind"] == "main" and r["status"] == "uploaded"), {})
        return {
            "answered": answer["status"] == "answered",
            "processing_status": answer.get("processing", {}).get("status"),
            "transcript": main.get("transcript"),
            "recording_id": main.get("recording_id"),
            # The stored evaluation has extra bookkeeping fields (like model);
            # the response models keep only the public ones.
            "evaluation": answer.get("evaluation"),
            "follow_ups": [
                {
                    "number": f["number"],
                    "question": f["question"],
                    "answered": f["status"] == "answered",
                    "recording_id": f.get("recording_id"),
                    "transcript": transcripts.get(f.get("recording_id")),
                }
                for f in sorted(answer.get("follow_ups", []), key=lambda f: f["number"])
            ],
        }

    # What should the interview screen show right now?
    current_step, follow_up_prompt = "record_answer", None
    if attempt["status"] == "completed":
        current_step = "finished"
    else:
        current = answers_by_order.get(attempt["current_question"])
        if current is not None and current["status"] == "evaluating":
            current_step = "evaluating"  # waiting for the worker's STAR check
        elif current is not None and current["status"] == "awaiting_follow_up":
            current_step = "record_follow_up"
            pending = pending_follow_up(current)
            follow_up_prompt = {"number": pending["number"], "question": pending["question"]}

    return {
        "attempt_id": str(attempt["_id"]),
        "interview_slug": interview["slug"],
        "interview_title": interview["title"],
        "status": attempt["status"],
        "current_question": attempt["current_question"],
        "current_step": current_step,
        "pending_follow_up": follow_up_prompt,
        "questions": [
            {"order": q["order"], "type": q["type"], "text": q["text"], **results_for(q["order"])}
            for q in sorted(interview["questions"], key=lambda q: q["order"])
        ],
        "limits": {
            "max_recording_seconds": settings.max_recording_seconds,
            "max_upload_bytes": settings.max_upload_bytes,
            "allowed_content_types": list(ALLOWED_CONTENT_TYPES),
            "max_follow_ups": settings.max_follow_ups,
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
# Uploading a recording (a main answer or a follow-up answer)
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

    # Is this recording the MAIN answer, or the answer to a FOLLOW-UP question?
    # The answer's status tells us.
    answer = await db.answers.find_one({"attempt_id": attempt["_id"], "question_order": order})
    follow_up_number = None
    if answer is None or answer["status"] == "recording":
        kind = "main"
    elif answer["status"] == "awaiting_follow_up":
        kind = "follow_up"
        follow_up_number = pending_follow_up(answer)["number"]
    elif answer["status"] == "evaluating":
        raise HTTPException(status_code=409, detail="We're still reviewing your answer - please wait a moment")
    else:
        raise HTTPException(status_code=409, detail="This question has already been answered")

    recording_id = uuid.uuid4().hex  # a random, unguessable ID
    label = "main" if kind == "main" else f"followup{follow_up_number}"
    # Where the file will live in the bucket. Grouping by user and attempt
    # makes it easy to find (or delete) everything belonging to one person.
    video_key = (
        f"videos/{user['cognito_sub']}/{attempt_id}/"
        f"q{order}-{label}-{recording_id}.{ALLOWED_CONTENT_TYPES[content_type]}"
    )
    now = datetime.now(UTC)
    recording = {
        "recording_id": recording_id,
        "kind": kind,
        "follow_up_number": follow_up_number,
        "video_key": video_key,
        "content_type": content_type,
        "size_bytes": body.size_bytes,
        "status": "awaiting_upload",
        "created_at": now,
        "uploaded_at": None,
    }

    # Keep every recording that's already uploaded, drop any unfinished one
    # (e.g. from an upload that failed), and add this new one.
    kept = [r for r in answer["recordings"] if r["status"] == "uploaded"] if answer else []

    # One answer document per question. "Upsert" creates it on the first
    # recording; after that, it just updates the list of recordings.
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
                "follow_ups": [],
                "visibility": "private",  # nobody else can see it (sharing comes in Phase 5)
                "created_at": now,
            },
            "$set": {"recordings": [*kept, recording]},
        },
        upsert=True,
    )

    # generate_presigned_url doesn't contact AWS - it just does maths with
    # your keys - but it's ordinary blocking code, so we run it in a thread.
    upload_url = await run_in_threadpool(storage.presign_upload, video_key, content_type, body.size_bytes)
    return {
        "recording_id": recording_id,
        "kind": kind,
        "follow_up_number": follow_up_number,
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
    queue: JobQueue = Depends(get_queue),
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
    updates = {
        "recordings": [
            {**r, "status": "uploaded", "uploaded_at": now} if r["recording_id"] == recording_id else r
            for r in answer["recordings"]
        ],
    }
    if recording["kind"] == "follow_up":
        # Link the follow-up question to the recording that answers it.
        updates["follow_ups"] = [
            {**f, "status": "answered", "recording_id": recording_id}
            if f["number"] == recording["follow_up_number"] else f
            for f in answer.get("follow_ups", [])
        ]

    # Situational answers wait for the worker's STAR check, which decides
    # whether to ask a follow-up. That's only possible if processing is set up;
    # otherwise the answer is simply accepted as it is.
    waits_for_star_check = answer["question_type"] == "situational" and queue.is_configured
    updates["status"] = "evaluating" if waits_for_star_check else "answered"
    if not waits_for_star_check:
        updates["answered_at"] = now

    # Only update if the answer is in the status we expect. If two requests
    # race each other, the second one finds nothing to update.
    expected_status = "recording" if recording["kind"] == "main" else "awaiting_follow_up"
    marked = await db.answers.update_one({"_id": answer["_id"], "status": expected_status}, {"$set": updates})

    # Only the request that actually updated the answer carries on, so a
    # double-click can never queue the same recording twice.
    if marked.modified_count == 1:
        queued = await queue_for_processing(db, queue, answer["_id"], recording_id)
        if not waits_for_star_check:
            await advance_attempt(db, attempt, order)
        elif not queued:
            # The STAR check can't happen, so don't leave the user waiting
            # forever: accept the answer as it is and move on.
            await db.answers.update_one(
                {"_id": answer["_id"]}, {"$set": {"status": "answered", "answered_at": now}}
            )
            await advance_attempt(db, attempt, order)

    fresh = await db.attempts.find_one({"_id": attempt["_id"]})
    return {"status": fresh["status"], "current_question": fresh["current_question"]}


async def queue_for_processing(db: AsyncDatabase, queue: JobQueue, answer_id: ObjectId, recording_id: str) -> bool:
    """Put a "transcribe and evaluate this" job onto the SQS queue. Returns True if it was sent."""
    now = datetime.now(UTC)
    if not queue.is_configured:
        await db.answers.update_one(
            {"_id": answer_id},
            {"$set": {"processing": {"status": "not_configured", "error": None, "updated_at": now}}},
        )
        return False

    # ORDER MATTERS: mark it "queued" BEFORE sending the job. The worker can
    # be very quick - if we sent first, it might set "transcribing" and then
    # this line would overwrite it with "queued", so the status went backwards.
    await db.answers.update_one(
        {"_id": answer_id},
        {"$set": {"processing": {"status": "queued", "error": None, "updated_at": now}}},
    )
    try:
        await run_in_threadpool(queue.send_processing_job, str(answer_id), recording_id)
        return True
    except Exception:
        # The video is safely stored either way; only the processing is missing.
        logger.exception("Couldn't queue answer %s for processing", answer_id)
        await db.answers.update_one(
            {"_id": answer_id},
            {"$set": {"processing": {"status": "failed", "error": "Couldn't start processing", "updated_at": now}}},
        )
        return False


# ---------------------------------------------------------------------------
# Watching a recording back
# ---------------------------------------------------------------------------

@router.get("/{attempt_id}/questions/{order}/video-url", response_model=VideoUrlResponse)
async def get_video_url(
    attempt_id: str,
    order: int,
    recording_id: str | None = None,  # optional "?recording_id=..." - the main answer if left out
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    storage: VideoStorage = Depends(get_storage),
):
    require_storage(storage)
    attempt = await load_own_attempt(db, attempt_id, user)  # <- the ownership check

    answer = await db.answers.find_one({"attempt_id": attempt["_id"], "question_order": order})
    uploaded = [r for r in (answer or {}).get("recordings", []) if r["status"] == "uploaded"]
    if recording_id is None:
        recording = next((r for r in uploaded if r["kind"] == "main"), None)
    else:
        recording = next((r for r in uploaded if r["recording_id"] == recording_id), None)
    if recording is None:
        raise HTTPException(status_code=404, detail="No recording found for this question")

    url = await run_in_threadpool(storage.presign_download, recording["video_key"])
    return {
        "url": url,
        "content_type": recording["content_type"],
        "expires_in_seconds": settings.video_url_expiry_seconds,
    }
