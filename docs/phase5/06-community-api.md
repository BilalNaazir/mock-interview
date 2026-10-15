# 06 The Community API

Three endpoints serve the Community pages:

| Endpoint | What it does | Uses AI? |
|---|---|---|
| `GET /community/answers` | List shared answers, optionally filtered | No: an ordinary database query |
| `GET /community/answers/{answer_id}` | One shared answer, in full | No |
| `POST /community/search` | Ask the search agent a question | Yes |

Two privacy rules hold in every one of them: **only shared answers are ever returned**, and **no names, emails, user IDs or videos are ever sent**.

---

## `backend/app/models.py`: the response shapes

**Where and when it's used:** FastAPI checks every Community response against these, and sends **only** the fields they list.

```python
class SharedAnswerSummary(BaseModel):
    answer_id: str
    interview_slug: str
    interview_title: str
    question_order: int
    question_type: Literal["knowledge", "situational"]
    question_text: str
    excerpt: str
    score: int | None
    is_mine: bool
```

- One card on the Community page: which question the answer is for, a short excerpt, and its score (`None` if it hasn't been scored).
- `is_mine` is `true` for your own shared answers, so the page can label them "your answer". It reveals nothing about anyone else: it only says whether the answer is *yours*.
- **What's missing is the point:** there's no field for the owner's name, email or user ID, or the video. Even though the database documents contain `user_sub` and `video_key`, Pydantic only sends the fields listed here, so they **can't** leak out, even by accident. There's a test that checks the response text for them (chapter 08).

```python
class SharedFollowUp(BaseModel):
    number: int
    question: str
    transcript: str | None
```

- One follow-up question and its transcript, for the full view.

```python
class SharedAnswerDetail(BaseModel):
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
```

- The full view of one shared answer: the main transcript, follow-ups, and the evaluation. `EvaluationOut` is the Phase 4 model, which is either a knowledge evaluation or a STAR one. Again, no video and no owner.

```python
class SearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
```

- What the browser sends to search. `Field(min_length=3, max_length=500)` makes Pydantic reject empty or enormous questions with a 422 error before our code runs. Limiting the length also caps how much text goes to Claude per search.

```python
class SearchResponse(BaseModel):
    reply: str
    answers: list[SharedAnswerSummary]
```

- The agent's reply, plus cards for the answers it chose.

---

## `backend/app/routers/community.py`

**Where and when it's used:** the Community pages in React call these endpoints (chapter 07). The router is added to the app in `main.py`.

### Imports and the router

```python
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
```

- `timedelta` is a length of time, used for "one hour ago".
- `Query` declares settings for values read from the address, like `?question_order=3`.
- `prefix="/community"` puts every endpoint in this file under `/community`. `tags` groups them in the automatic docs at `/docs`.

### Two shared building blocks

```python
SHARED = {"visibility": "shared", "status": "answered"}
```

- The filter "shared and finished". Every query in this file starts from it, so "shared only" can't be forgotten in one endpoint.

```python
NO_EMBEDDING = {"embedding": 0}
```

- A projection meaning "every field **except** `embedding`". Those 1024 numbers are about 8 KB per answer of data nobody here needs, so they're never loaded.

### Small helpers

```python
def main_transcript(answer: dict) -> str | None:
    main = next((r for r in answer["recordings"] if r["kind"] == "main"), {})
    return main.get("transcript")
```

- Finds the main recording's transcript (or `None`). Used by `to_summary` and by the full view.

```python
async def interview_titles(db: AsyncDatabase) -> dict[str, str]:
    interviews = await db.interviews.find({}, {"slug": 1, "title": 1}).to_list()
    return {i["slug"]: i["title"] for i in interviews}
```

- Returns a lookup from slug to title, like `{"agentic-ai": "Agentic AI", ...}`, so cards can show "Agentic AI" instead of `agentic-ai`. Loading all five once per request is simpler than looking up each answer's interview separately.

```python
def to_summary(answer: dict, titles: dict, user: dict) -> dict:
    evaluation = answer.get("evaluation") or {}
```

- Turns an answer document into the shape of `SharedAnswerSummary`. It's used by all three endpoints. `or {}` means "if there's no evaluation, use an empty dictionary", so the next lines don't need special cases.

```python
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
```

- `str(answer["_id"])`: MongoDB's ID object turned into text for JSON.
- `titles.get(slug, slug)`: the title, or the slug itself if the interview were ever missing.
- `[:280]`: the first 280 characters of the main transcript, enough for a card.
- `is_mine`: compares the answer's owner with the logged-in user. The owner's ID is used here to work out `true` or `false`, but is never itself put in the response.

### Listing shared answers

```python
@router.get("/answers", response_model=list[SharedAnswerSummary])
async def list_shared_answers(
    interview_slug: str | None = None,
    question_order: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=50),
    skip: int = Query(default=0, ge=0),
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
```

- `GET /community/answers`, which returns a list of summaries.
- Parameters that aren't in the path, like `interview_slug`, come from the **query string**: `/community/answers?interview_slug=agentic-ai&question_order=3`. `= None` makes them optional.
- `Query(ge=1, le=5)` means "greater than or equal to 1, less than or equal to 5", so FastAPI rejects `question_order=99` with 422.
- `limit` and `skip` allow **pagination**: up to 20 answers per page by default (50 at most), and `skip` jumps past ones already shown. The page doesn't use `skip` yet, but it's ready for "load more".
- `user` makes this endpoint login-only.

```python
    query = dict(SHARED)
    if interview_slug:
        query["interview_slug"] = interview_slug
    if question_order:
        query["question_order"] = question_order
```

- `dict(SHARED)` makes a **copy** of the shared filter, so adding to it doesn't change `SHARED` itself for later requests. Then the optional filters are added if they were given.

```python
    answers = await (
        db.answers.find(query, NO_EMBEDDING).sort("answered_at", -1).skip(skip).limit(limit).to_list()
    )
```

- Finds matching answers without their embeddings, newest first (`-1` means descending), skips and limits for paging, and reads them into a list. The `visibility` + `answered_at` index from chapter 01 makes this fast.

```python
    titles = await interview_titles(db)
    return [to_summary(answer, titles, user) for answer in answers]
```

- Turns each document into a summary.

### Viewing one shared answer

```python
@router.get("/answers/{answer_id}", response_model=SharedAnswerDetail)
async def get_shared_answer(
    answer_id: str,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    not_found = HTTPException(status_code=404, detail="Shared answer not found")
    if not ObjectId.is_valid(answer_id):
        raise not_found
```

- Prepares one "not found" error, used in two places. An ID that isn't in MongoDB's format can't exist, so it's rejected straight away.

```python
    answer = await db.answers.find_one({"_id": ObjectId(answer_id), **SHARED}, NO_EMBEDDING)
    if answer is None:
        raise not_found
```

- `{"_id": ..., **SHARED}` combines "this ID" with "shared and finished". So a **private** answer isn't found, and gets exactly the same 404 as an answer that doesn't exist. That way, the response doesn't even reveal that a private answer with this ID exists, the same rule as the attempts endpoints.

```python
    transcripts = {r["recording_id"]: r.get("transcript") for r in answer["recordings"]}
    titles = await interview_titles(db)
```

- A lookup from recording ID to transcript, for matching follow-ups to their answers.

```python
    return {
        **to_summary(answer, titles, user),
        "transcript": main_transcript(answer),
```

- `**to_summary(...)` copies every field of the summary into this dictionary, then the full-view fields are added.

```python
        "follow_ups": [
            {"number": f["number"], "question": f["question"], "transcript": transcripts.get(f.get("recording_id"))}
            for f in sorted(answer.get("follow_ups", []), key=lambda f: f["number"])
            if f.get("recording_id")  # only follow-ups that were answered
        ],
        "evaluation": answer.get("evaluation"),
    }
```

- Each answered follow-up, in order, with its transcript. The `if` at the end of the list comprehension skips any that weren't answered.
- The evaluation is passed through, and `EvaluationOut` drops internal fields such as which model marked it.

### Getting the search agent

```python
def get_search_agent(request: Request) -> SearchAgent | None:
    return request.app.state.search_agent
```

- A FastAPI dependency returning the agent created at startup, or `None` if search is switched off. Because it's a dependency, tests replace it with a stand-in using `dependency_overrides`.

### Searching

```python
@router.post("/search", response_model=SearchResponse)
async def search_shared_answers(
    body: SearchRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    agent: SearchAgent | None = Depends(get_search_agent),
):
```

- `POST /community/search`. It's a POST rather than a GET because it sends a body (the question), and because each search has a cost and is logged.

```python
    if agent is None:
        raise HTTPException(status_code=503, detail="Search isn't available right now")
```

- If search is switched off, answer 503 ("service unavailable") with a friendly message.

```python
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    recent = await db.search_log.count_documents(
        {"user_sub": user["cognito_sub"], "created_at": {"$gte": one_hour_ago}}
    )
```

- **The cost guardrail.** Counts this user's searches since an hour ago. `$gte` means "greater than or equal to", so "created at or after one hour ago". The `search_log` index from chapter 01 makes this count fast.

```python
    if recent >= settings.searches_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You've reached the limit of {settings.searches_per_hour} searches an hour. Please try later.",
        )
```

- At or over the limit (30 by default): refuse with **429 "too many requests"**, the standard status code for rate limiting.

```python
    await db.search_log.insert_one(
        {"user_sub": user["cognito_sub"], "question": body.question, "created_at": datetime.now(UTC)}
    )
```

- Records this search **before** running it, so even a search that fails counts towards the limit (it may still have cost something). The TTL index deletes these records after 7 days.

```python
    result = await agent.run(body.question)
    titles = await interview_titles(db)
    return {"reply": result["reply"], "answers": [to_summary(a, titles, user) for a in result["answers"]]}
```

- Runs the agent (chapter 05), then turns the answers it chose into summaries. These answers came from vector search, which only returns shared ones, and `to_summary` plus `SharedAnswerSummary` mean nothing private is included.
