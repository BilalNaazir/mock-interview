"""
community.py - Browsing and searching answers that candidates have shared.

  GET  /community/answers              -> list shared answers (optionally filtered)
  GET  /community/answers/{answer_id}  -> one shared answer, in full
  POST /community/search               -> ask the search agent a question

PRIVACY RULES, enforced in every endpoint:
  - Only answers with visibility "shared" are ever returned. A private
    answer gets the same 404 as one that doesn't exist.
  - No names, emails, user IDs or videos are sent: only transcripts and
    feedback. The response models in models.py simply have no such fields.
"""

from datetime import UTC, datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo.asynchronous.database import AsyncDatabase

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models import SearchRequest, SearchResponse, SharedAnswerDetail, SharedAnswerSummary
from app.search_agent import SearchAgent

router = APIRouter(prefix="/community", tags=["community"])

# Every query in this file starts from this, so "shared only" can't be forgotten.
SHARED = {"visibility": "shared", "status": "answered"}
# Never load the 1024-number embedding when we don't need it.
NO_EMBEDDING = {"embedding": 0}


def main_transcript(answer: dict) -> str | None:
    main = next((r for r in answer["recordings"] if r["kind"] == "main"), {})
    return main.get("transcript")


async def interview_titles(db: AsyncDatabase) -> dict[str, str]:
    interviews = await db.interviews.find({}, {"slug": 1, "title": 1}).to_list()
    return {i["slug"]: i["title"] for i in interviews}


def to_summary(answer: dict, titles: dict, user: dict) -> dict:
    """Turn an answer document into a SharedAnswerSummary-shaped dict."""
    evaluation = answer.get("evaluation") or {}
    return {
        "answer_id": str(answer["_id"]),
        "interview_slug": answer["interview_slug"],
        "interview_title": titles.get(answer["interview_slug"], answer["interview_slug"]),
        "question_order": answer["question_order"],
        "question_type": answer["question_type"],
        "question_text": answer["question_text"],
        "excerpt": (main_transcript(answer) or "")[:280],
        "score": evaluation.get("score"),
        "is_mine": answer["user_sub"] == user["cognito_sub"],
    }


@router.get("/answers", response_model=list[SharedAnswerSummary])
async def list_shared_answers(
    # Query(...) declares optional "?interview_slug=...&question_order=..." values.
    interview_slug: str | None = None,
    question_order: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=50),
    skip: int = Query(default=0, ge=0),
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    query = dict(SHARED)
    if interview_slug:
        query["interview_slug"] = interview_slug
    if question_order:
        query["question_order"] = question_order

    answers = await (
        db.answers.find(query, NO_EMBEDDING).sort("answered_at", -1).skip(skip).limit(limit).to_list()
    )
    titles = await interview_titles(db)
    return [to_summary(answer, titles, user) for answer in answers]


@router.get("/answers/{answer_id}", response_model=SharedAnswerDetail)
async def get_shared_answer(
    answer_id: str,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    not_found = HTTPException(status_code=404, detail="Shared answer not found")
    if not ObjectId.is_valid(answer_id):
        raise not_found
    answer = await db.answers.find_one({"_id": ObjectId(answer_id), **SHARED}, NO_EMBEDDING)
    if answer is None:
        raise not_found

    transcripts = {r["recording_id"]: r.get("transcript") for r in answer["recordings"]}
    titles = await interview_titles(db)
    return {
        **to_summary(answer, titles, user),
        "transcript": main_transcript(answer),
        "follow_ups": [
            {"number": f["number"], "question": f["question"], "transcript": transcripts.get(f.get("recording_id"))}
            for f in sorted(answer.get("follow_ups", []), key=lambda f: f["number"])
            if f.get("recording_id")  # only follow-ups that were answered
        ],
        "evaluation": answer.get("evaluation"),
    }


def get_search_agent(request: Request) -> SearchAgent | None:
    """FastAPI dependency: the agent created at startup, or None if search is switched off."""
    return request.app.state.search_agent


@router.post("/search", response_model=SearchResponse)
async def search_shared_answers(
    body: SearchRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: SearchAgent | None = Depends(get_search_agent),
):
    if agent is None:
        raise HTTPException(status_code=503, detail="Search isn't available right now")

    # COST GUARDRAIL: each search calls Claude and Voyage, so limit how many
    # one person can run per hour. search_log keeps a record of each search.
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    recent = await db.search_log.count_documents(
        {"user_sub": user["cognito_sub"], "created_at": {"$gte": one_hour_ago}}
    )
    if recent >= settings.searches_per_hour:
        # 429 = "too many requests"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You've reached the limit of {settings.searches_per_hour} searches an hour. Please try later.",
        )
    await db.search_log.insert_one(
        {"user_sub": user["cognito_sub"], "question": body.question, "created_at": datetime.now(UTC)}
    )

    result = await agent.run(body.question)
    titles = await interview_titles(db)
    return {"reply": result["reply"], "answers": [to_summary(a, titles, user) for a in result["answers"]]}
