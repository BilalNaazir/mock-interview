"""
models.py - The exact shape of the data our API sends back.

These are Pydantic models. They do two jobs:
  1. FastAPI uses them to CHECK responses. If an endpoint tries to return
     data missing a required field, you get an error during development
     instead of the frontend quietly receiving broken data.
  2. They act as a FILTER: only the fields listed here are sent. So even if
     a database document holds private fields (like a scoring rubric we'll
     add later), they can't leak out by accident.

They also appear automatically in the API docs at http://localhost:8000/docs.
The frontend has matching TypeScript types in frontend/src/types.ts.
"""

from typing import Literal

from pydantic import BaseModel


class Question(BaseModel):
    order: int                                      # 1 to 5
    type: Literal["knowledge", "situational"]
    text: str


class InterviewSummary(BaseModel):
    """What the interview list page needs: no questions, just the overview."""
    slug: str            # a URL-friendly ID, e.g. "backend-python"
    title: str
    description: str
    question_count: int


class InterviewDetail(BaseModel):
    slug: str
    title: str
    description: str
    questions: list[Question]


class UserProfile(BaseModel):
    email: str
    name: str
    share_answers_by_default: bool


class HealthStatus(BaseModel):
    status: Literal["ok"]
    environment: str
