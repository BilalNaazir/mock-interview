"""
processing.py - What the worker does with ONE job from the queue.

For each submitted recording:
  1. Download the video from S3 to a temporary file
  2. Transcribe it with Whisper
  3. Evaluate it:
       - KNOWLEDGE answers: score against the private key_points rubric
       - SITUATIONAL answers (Phase 4): check the whole conversation so far
         against STAR, then either ASK A FOLLOW-UP or ACCEPT the answer
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
from app.interview_flow import next_question_fields
from app.queue import ReceivedJob
from app.scoring import Exchange, Scorer
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


def accept_answer_and_move_on(db: Database, answer: dict) -> None:
    """
    Mark a situational answer as finished and move the interview to the next
    question. Only acts if the answer is still "evaluating", so running it
    twice by accident does nothing the second time.
    """
    now = datetime.now(UTC)
    accepted = db.answers.update_one(
        {"_id": answer["_id"], "status": "evaluating"},
        {"$set": {"status": "answered", "answered_at": now}},
    )
    if accepted.modified_count == 1:
        attempt = db.attempts.find_one({"_id": answer["attempt_id"]})
        db.attempts.update_one(
            # Same safety rule as the API: only move forward from this question.
            {"_id": attempt["_id"], "current_question": answer["question_order"]},
            {"$set": next_question_fields(answer["question_order"], attempt["question_count"], now)},
        )


def build_exchanges(answer: dict, recordings: list[dict]) -> list[Exchange]:
    """
    The conversation so far, in order: the original question and its answer,
    then each follow-up question and its answer (if it has been answered).
    """
    transcripts = {r["recording_id"]: r.get("transcript") for r in recordings}
    main = next(r for r in recordings if r["kind"] == "main")
    exchanges = [Exchange(question=answer["question_text"], transcript=main.get("transcript") or "")]
    for follow_up in sorted(answer.get("follow_ups", []), key=lambda f: f["number"]):
        transcript = transcripts.get(follow_up.get("recording_id"))
        if transcript is not None:
            exchanges.append(Exchange(question=follow_up["question"], transcript=transcript))
    return exchanges


def evaluate_situational(answer: dict, recordings: list[dict], ctx: WorkerContext) -> str:
    """Check the answer against STAR, then ask a follow-up or accept it."""
    star = ctx.scorer.evaluate_star(build_exchanges(answer, recordings))
    now = datetime.now(UTC)
    follow_ups = answer.get("follow_ups", [])
    evaluation = {
        "kind": "star",
        "score": star.score,  # worked out by our code from the ratings
        "feedback": star.feedback,
        "situation": star.situation.model_dump(),
        "task": star.task.model_dump(),
        "action": star.action.model_dump(),
        "result": star.result.model_dump(),
        "model": ctx.settings.scoring_model,
    }

    # THE DECISION. The AI suggests a follow-up question, but our CODE decides
    # whether to ask it - and it can never go past the limit, whatever the AI says.
    wants_follow_up = bool(star.weak_elements()) and bool(star.follow_up_question.strip())
    if wants_follow_up and len(follow_ups) < ctx.settings.max_follow_ups:
        follow_up = {
            "number": len(follow_ups) + 1,
            "question": star.follow_up_question.strip(),
            "targets": star.weak_elements(),  # which STAR elements it's chasing
            "status": "awaiting_answer",
            "recording_id": None,
            "asked_at": now,
        }
        ctx.db.answers.update_one(
            {"_id": answer["_id"], "status": "evaluating"},
            {"$set": {
                "follow_ups": [*follow_ups, follow_up],
                "status": "awaiting_follow_up",
                "evaluation": evaluation,  # the latest check, so far
            }},
        )
        return f"asked follow-up {follow_up['number']}"

    # Everything's clear, or we've asked enough: accept the answer.
    ctx.db.answers.update_one({"_id": answer["_id"]}, {"$set": {"evaluation": evaluation}})
    accept_answer_and_move_on(ctx.db, answer)
    return "accepted answer"


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
    # attempts.py), so it's kept even if evaluation fails afterwards.
    recordings = [
        {**r, "transcript": transcript} if r["recording_id"] == recording_id else r
        for r in answer["recordings"]
    ]
    ctx.db.answers.update_one({"_id": answer_id}, {"$set": {"recordings": recordings}})

    # --- 3: evaluate -----------------------------------------------------------
    set_processing_status(ctx.db, answer_id, "scoring")
    if answer["question_type"] == "knowledge":
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
        outcome = "scored knowledge answer"
    else:
        outcome = evaluate_situational(answer, recordings, ctx)

    # --- 4: done -----------------------------------------------------------
    set_processing_status(ctx.db, answer_id, "done")
    return outcome


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
                # A situational answer blocks the interview while it's being
                # evaluated. If evaluation is impossible, accept the answer as it
                # is, so the candidate is never stuck on a question forever.
                answer = ctx.db.answers.find_one({"_id": ObjectId(answer_id)})
                if answer is not None and answer["status"] == "evaluating":
                    accept_answer_and_move_on(ctx.db, answer)
            else:
                # Not deleting the job means SQS hands it out again after
                # the visibility timeout - an automatic retry.
                set_processing_status(
                    ctx.db, ObjectId(answer_id), "queued", error=f"Retrying after an error: {type(error).__name__}"
                )
        return False
