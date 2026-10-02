"""
interviews.py - Listing interviews and viewing one interview's questions.

Notice the difference in protection between the two endpoints:
  - GET /interviews          -> PUBLIC. Anyone can see which interviews exist,
                                so the home page works before logging in.
  - GET /interviews/{slug}   -> PROTECTED. You must be logged in to see the
                                questions (and, later, to take the interview).
"""

from fastapi import APIRouter, Depends, HTTPException
from pymongo.asynchronous.database import AsyncDatabase

from app.auth import get_current_user
from app.db import get_db
from app.models import InterviewDetail, InterviewSummary

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.get("", response_model=list[InterviewSummary])
async def list_interviews(db: AsyncDatabase = Depends(get_db)):
    # A PROJECTION ({"field": 1, ...}) tells MongoDB which fields to return.
    # "questions.order" fetches just each question's number, not its full
    # text and rubric - enough to count them, without the extra data.
    cursor = db.interviews.find(
        {},
        {"_id": 0, "slug": 1, "title": 1, "description": 1, "questions.order": 1},
    ).sort("title", 1)

    interviews = await cursor.to_list()
    return [
        {
            "slug": doc["slug"],
            "title": doc["title"],
            "description": doc["description"],
            "question_count": len(doc["questions"]),
        }
        for doc in interviews
    ]


@router.get("/{slug}", response_model=InterviewDetail)
async def get_interview(
    slug: str,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),  # <- this line makes it login-only
):
    interview = await db.interviews.find_one({"slug": slug}, {"_id": 0})
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    # The document includes each question's private key_points, but the
    # InterviewDetail/Question models only contain order, type and text,
    # so the rubric is stripped out before the response is sent.
    return interview
