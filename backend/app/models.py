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

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------------------
# Phase 2: taking an interview
#
# An ATTEMPT is one run through an interview by one user. Each question in it
# gets an ANSWER, and each answer holds one or more RECORDINGS: the main
# answer now, plus follow-up answers for situational questions in Phase 4.
# ---------------------------------------------------------------------------

AttemptStatus = Literal["in_progress", "completed"]


class StartAttemptRequest(BaseModel):
    interview_slug: str
    # The user must actively agree to being recorded. We store WHEN they agreed.
    consent_to_recording: bool


class StartAttemptResponse(BaseModel):
    attempt_id: str
    resumed: bool  # True if an unfinished attempt already existed and was reused


class AttemptQuestion(BaseModel):
    order: int
    type: Literal["knowledge", "situational"]
    text: str
    answered: bool


class RecordingLimits(BaseModel):
    """Sent to the browser so the recorder enforces the same limits as the backend."""
    max_recording_seconds: int
    max_upload_bytes: int
    allowed_content_types: list[str]


class AttemptDetail(BaseModel):
    attempt_id: str
    interview_slug: str
    interview_title: str
    status: AttemptStatus
    current_question: int  # the question being answered now (6 once all 5 are done)
    questions: list[AttemptQuestion]
    limits: RecordingLimits


class AttemptSummary(BaseModel):
    attempt_id: str
    interview_slug: str
    interview_title: str
    status: AttemptStatus
    answered_count: int
    question_count: int
    started_at: datetime


class UploadUrlRequest(BaseModel):
    content_type: str
    # Field(gt=0) means "must be greater than 0" - Pydantic rejects anything else.
    size_bytes: int = Field(gt=0)


class UploadUrlResponse(BaseModel):
    recording_id: str
    upload_url: str
    # The browser MUST send exactly these headers with the upload,
    # because they're part of the presigned URL's signature.
    upload_headers: dict[str, str]
    expires_in_seconds: int


class CompleteRecordingResponse(BaseModel):
    status: AttemptStatus
    current_question: int


class VideoUrlResponse(BaseModel):
    url: str
    content_type: str
    expires_in_seconds: int
