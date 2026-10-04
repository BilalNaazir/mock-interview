"""
processing.py - What the worker does with ONE job from the queue.

For each submitted recording:
  1. Download the video from S3 to a temporary file
  2. Transcribe it with Whisper
  3. If it's a knowledge question, score it with Claude against the rubric
     (situational questions get STAR evaluation in Phase 4)
  4. Save everything to MongoDB

Along the way it updates answer.processing.status, which the browser sees
live through the WebSocket:  queued -> transcribing -> scoring -> done

This file uses PyMongo's ordinary (non-async) client. The worker does one
job at a time, so the async style the web server needs brings no benefit.

The slow and costly parts (Whisper, Claude) are passed in as arguments, so
the tests can swap in fakes - the same reason storage.py and queue.py exist.
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.database import Database

from app.config import Settings
from app.queue import ReceivedJob
from app.scoring import Scorer
from app.storage import VideoStorage
from app.transcription import Transcriber

logger = logging.getLogger("mock_interview.processing")


@dataclass
class WorkerContext:
    """Everything the worker needs, bundled together."""
    db: Database
    storage: VideoStorage
    transcriber: Transcriber
    scorer: Scorer
    settings: Settings


def set_processing_status(db: Database, answer_id: ObjectId, status: str, error: str | None = None) -> None:
    db.answers.update_one(
        {"_id": answer_id},
        {"$set": {"processing": {"status": status, "error": error, "updated_at": datetime.now(UTC)}}},
    )


def process_recording(job_body: dict, ctx: WorkerContext) -> str:
    """Process one recording. Returns a short description of what happened."""
    if not ObjectId.is_valid(job_body.get("answer_id", "")):
        return "skipped: invalid answer id"
    answer_id = ObjectId(job_body["answer_id"])
    recording_id = job_body.get("recording_id")

    answer = ctx.db.answers.find_one({"_id": answer_id})
    if answer is None:
        return "skipped: answer no longer exists"  # e.g. the user deleted it
    recording = next((r for r in answer["recordings"] if r["recording_id"] == recording_id), None)
    if recording is None:
        return "skipped: recording no longer exists"

    # IDEMPOTENT: SQS can occasionally deliver the same job twice. If this
    # recording is already done, don't transcribe it (or pay for scoring) again.
    if recording.get("transcript") is not None and answer.get("processing", {}).get("status") == "done":
        return "skipped: already processed"

    # --- 1 and 2: download and transcribe ---------------------------------
    set_processing_status(ctx.db, answer_id, "transcribing")
    extension = recording["video_key"].rsplit(".", 1)[-1]
    # A temporary folder is deleted automatically afterwards, so videos never
    # pile up on the worker's disk.
    with tempfile.TemporaryDirectory() as folder:
        local_path = os.path.join(folder, f"answer.{extension}")
        ctx.storage.download_to_file(recording["video_key"], local_path)
        transcript = ctx.transcriber.transcribe(local_path)

    # Save the transcript onto this recording (rebuilding the list, as in
    # attempts.py), so it's kept even if scoring fails afterwards.
    recordings = [
        {**r, "transcript": transcript} if r["recording_id"] == recording_id else r
        for r in answer["recordings"]
    ]
    ctx.db.answers.update_one({"_id": answer_id}, {"$set": {"recordings": recordings}})

    # --- 3: score knowledge answers ----------------------------------------
    if answer["question_type"] == "knowledge":
        set_processing_status(ctx.db, answer_id, "scoring")
        interview = ctx.db.interviews.find_one({"slug": answer["interview_slug"]})
        question = next(q for q in interview["questions"] if q["order"] == answer["question_order"])
        evaluation = ctx.scorer.score_knowledge_answer(
            question=answer["question_text"],
            key_points=question["key_points"],
            transcript=transcript,
        )
        ctx.db.answers.update_one(
            {"_id": answer_id},
            {"$set": {"evaluation": {
                **evaluation.model_dump(),
                "kind": "knowledge",
                "model": ctx.settings.scoring_model,  # which model marked it, for reference
            }}},
        )

    # --- 4: done -----------------------------------------------------------
    set_processing_status(ctx.db, answer_id, "done")
    return "processed"


def handle_job(job: ReceivedJob, ctx: WorkerContext) -> bool:
    """
    Run one job and decide what happens to it.
    Returns True if the job should be DELETED from the queue.
    """
    try:
        outcome = process_recording(job.body, ctx)
        logger.info("Job %s: %s", job.body, outcome)
        return True
    except Exception as error:
        # logger.exception records the full error details for debugging.
        logger.exception("Job %s failed (attempt %s)", job.body, job.receive_count)
        answer_id = job.body.get("answer_id", "")
        if ObjectId.is_valid(answer_id):
            if job.receive_count >= ctx.settings.max_processing_attempts:
                # Out of tries. We still DON'T delete the job: SQS moves it to
                # the dead-letter queue, where you can inspect it later. We
                # just mark the answer as failed, so the user isn't left waiting.
                set_processing_status(
                    ctx.db, ObjectId(answer_id), "failed", error="Processing failed. Please try again later."
                )
            else:
                # Not deleting the job means SQS hands it out again after
                # the visibility timeout - an automatic retry.
                set_processing_status(
                    ctx.db, ObjectId(answer_id), "queued", error=f"Retrying after an error: {type(error).__name__}"
                )
        return False
