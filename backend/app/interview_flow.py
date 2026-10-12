"""
interview_flow.py - The rules of moving through an interview.

Both the API (async) and the worker (sync) need these rules, so they live in
one place. If both had their own copy, they could quietly drift apart.

How an ANSWER moves through its statuses:

  Knowledge question:
      recording -> answered
      (scoring then happens in the background while you carry on)

  Situational question (Phase 4):
      recording -> evaluating -> answered
                       |
                       +-> awaiting_follow_up -> evaluating -> ... (up to 3 times)

  "evaluating" means the worker is transcribing the latest recording and
  checking the whole answer so far against STAR. Then it either asks a
  follow-up question or accepts the answer.
"""

from datetime import datetime

STAR_ELEMENTS = ("situation", "task", "action", "result")

# Points per STAR element, by rating. Four elements x 25 = 100.
# The SCORE is worked out by our code, not by the AI: the AI judges each
# element, and simple, transparent arithmetic turns that into a number.
STAR_POINTS = {"clear": 25, "partial": 12, "missing": 0}


def star_score(ratings: dict[str, str]) -> int:
    return sum(STAR_POINTS[ratings[element]] for element in STAR_ELEMENTS)


def next_question_fields(order: int, question_count: int, now: datetime) -> dict:
    """The attempt fields to set after question `order` is finished."""
    next_question = order + 1
    finished = next_question > question_count
    return {
        "current_question": next_question,
        "status": "completed" if finished else "in_progress",
        "completed_at": now if finished else None,
    }
