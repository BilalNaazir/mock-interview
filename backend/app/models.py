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
from typing import Annotated, Literal

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


# Where an answer is in the processing pipeline (Phase 3). The browser shows
# this, and the WebSocket announces each change.
# Phase 5: "private" answers are only visible to their owner; "shared" ones
# appear on the Community pages and in search.
Visibility = Literal["private", "shared"]

ProcessingStatus = Literal["queued", "transcribing", "scoring", "done", "failed", "not_configured"]


class KnowledgeEvaluationOut(BaseModel):
    kind: Literal["knowledge"]
    score: int
    covered_points: list[str]
    missing_points: list[str]
    feedback: str


class StarElementOut(BaseModel):
    rating: Literal["clear", "partial", "missing"]
    comment: str


class StarEvaluationOut(BaseModel):
    kind: Literal["star"]
    score: int
    feedback: str
    situation: StarElementOut
    task: StarElementOut
    action: StarElementOut
    result: StarElementOut


# A "discriminated union": an evaluation is EITHER a knowledge one OR a STAR
# one, and the "kind" field says which. Pydantic reads "kind" first and then
# checks the rest of the fields against the right model.
EvaluationOut = Annotated[KnowledgeEvaluationOut | StarEvaluationOut, Field(discriminator="kind")]


class FollowUpOut(BaseModel):
    number: int                 # 1, 2 or 3
    question: str
    answered: bool
    recording_id: str | None    # for playing the follow-up answer back
    transcript: str | None


class AttemptQuestion(BaseModel):
    order: int
    type: Literal["knowledge", "situational"]
    text: str
    answered: bool
    # Phase 3: filled in by the worker. None until there's something to show.
    processing_status: ProcessingStatus | None = None
    transcript: str | None = None
    recording_id: str | None = None
    evaluation: EvaluationOut | None = None
    # Phase 4: follow-up questions asked about a situational answer.
    follow_ups: list[FollowUpOut] = []
    # Phase 5: whether other candidates can see this answer.
    visibility: Visibility = "private"


class PendingFollowUp(BaseModel):
    number: int
    question: str


# What the interview screen should show right now:
#   record_answer     -> record the main answer to the current question
#   evaluating        -> wait: the worker is checking the answer against STAR
#   record_follow_up  -> record an answer to the follow-up question
#   finished          -> all done
CurrentStep = Literal["record_answer", "evaluating", "record_follow_up", "finished"]


class RecordingLimits(BaseModel):
    """Sent to the browser so the recorder enforces the same limits as the backend."""
    max_recording_seconds: int
    max_upload_bytes: int
    allowed_content_types: list[str]
    max_follow_ups: int


class AttemptDetail(BaseModel):
    attempt_id: str
    interview_slug: str
    interview_title: str
    status: AttemptStatus
    current_question: int  # the question being answered now (6 once all 5 are done)
    current_step: CurrentStep
    pending_follow_up: PendingFollowUp | None  # set when current_step is "record_follow_up"
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
    kind: Literal["main", "follow_up"]
    follow_up_number: int | None
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


# ---------------------------------------------------------------------------
# Phase 5: sharing and the Community pages
#
# PRIVACY: none of these models has a field for the owner's name, email,
# user ID, or the video. Pydantic only sends the fields listed in a model, so
# those can never leak out of these endpoints - even by accident.
# ---------------------------------------------------------------------------

class VisibilityRequest(BaseModel):
    visibility: Visibility


class VisibilityResponse(BaseModel):
    visibility: Visibility
    changed: int  # how many answers were updated


class SharedAnswerSummary(BaseModel):
    """One card on the Community page."""
    answer_id: str
    interview_slug: str
    interview_title: str
    question_order: int
    question_type: Literal["knowledge", "situational"]
    question_text: str
    excerpt: str
    score: int | None
    is_mine: bool  # lets the page say "Your answer" - without revealing anyone else


class SharedFollowUp(BaseModel):
    number: int
    question: str
    transcript: str | None


class SharedAnswerDetail(BaseModel):
    """The full view of one shared answer: transcripts and feedback, no video."""
    answer_id: str
    interview_slug: str
    interview_title: str
    question_order: int
    question_type: Literal["knowledge", "situational"]
    question_text: str
    transcript: str | None
    follow_ups: list[SharedFollowUp]
    evaluation: EvaluationOut | None
    is_mine: bool


class SearchRequest(BaseModel):
    # min_length / max_length: Pydantic rejects empty or huge questions
    # before our code even runs (a 422 error).
    question: str = Field(min_length=3, max_length=500)


class SearchResponse(BaseModel):
    reply: str
    answers: list[SharedAnswerSummary]
