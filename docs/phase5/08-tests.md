# 08 The tests

Phase 5 adds **36 tests** (104 in total). Like earlier phases, the real code runs against a real test database, and only the outside world is faked: Voyage, Claude, and MongoDB's vector search, which plain MongoDB in GitHub Actions doesn't have.

Run them from `backend` with:

```
pytest -v
```

or just this phase's, by file name, for example `pytest tests/test_search_agent.py -v`.

---

## `tests/conftest.py`: two changes

**Where and when it's used:** pytest runs this file automatically before any test.

```python
os.environ["CREATE_VECTOR_INDEX"] = "false"
os.environ["VOYAGE_API_KEY"] = ""
```

- Set **before** the app is imported (settings are read once, as explained in Phase 3).
- `CREATE_VECTOR_INDEX=false`: the app doesn't try to create a real vector index at startup. Tests use a pretend search instead, so the tests behave the same on your laptop (which has vector search) and in GitHub Actions (which doesn't).
- `VOYAGE_API_KEY=""`: makes sure a real key from your `.env` file can never be used by a test. Environment variables set here win over `.env`.

```python
    db.search_log.delete_many({})
```

- Added to the `fresh_attempts` fixture, which runs before every test. It empties the search log, so one test's searches don't count towards another test's hourly limit.

---

## `tests/helpers.py`: the fakes

**Where and when it's used:** imported by the Phase 5 test files.

### Imports

```python
import math  # noqa: E402
import re  # noqa: E402
import zlib  # noqa: E402

from app.vector_search import FILTER_FIELDS, AnswerSearch  # noqa: E402
```

- `math` for square roots, `re` for finding words, `zlib` for a quick checksum.
- `# noqa: E402` tells the linter (ruff) not to complain that these imports are halfway down the file instead of at the top. They sit with the Phase 5 helpers they belong to.

### A pretend embedding

```python
DIMENSIONS = 1024


def word_vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
```

- Starts with 1024 zeros. `[0.0] * 1024` makes a list of 1024 copies of `0.0`.

```python
    for word in re.findall(r"[a-z]+", text.lower()):
        vector[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
```

- `text.lower()` lowercases the text, and `re.findall(r"[a-z]+", ...)` pulls out each word (runs of letters).
- For each word, `zlib.crc32` turns it into a big number (a **checksum**, which is always the same for the same word), and `% 1024` (the remainder after dividing by 1024) picks one of the 1024 slots. That slot goes up by 1.
- So "LangSmith" always adds to the same slot. Two texts that share words have numbers in the same slots, which makes their vectors similar. It's a crude stand-in for meaning, but good enough to test that search ranks a LangSmith answer above a Docker one.

```python
    length = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / length for v in vector]
```

- Scales the vector to a length of 1 (dividing every number by the vector's length), which is how real embeddings come back. `or 1.0` avoids dividing by zero for a text with no words.

### A pretend Voyage

```python
class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail = fail
        self.documents = []
        self.queries = []
```

- Has both methods a real `VoyageEmbedder` has, so it fits both Protocols. It records every text it's given (so tests can check what was embedded), and can be told to fail.

```python
    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("Voyage is down")
        self.documents.extend(texts)
        return [word_vector(text) for text in texts]

    async def embed_query(self, text):
        self.queries.append(text)
        return word_vector(text)
```

- `embed_documents` either fails on purpose, or records the texts and returns pretend embeddings. `embed_query` does the same for a query.

### A pretend vector search

```python
class InMemoryAnswerSearch(AnswerSearch):
```

- **Inherits** from the real `AnswerSearch`, so it's accepted anywhere an `AnswerSearch` is, but replaces its `search` method.

```python
    def __init__(self, db, settings):
        super().__init__(db, settings, available=True)
        self.calls = []
```

- `super().__init__(...)` runs the real class's setup. `calls` records the filters of every search, so tests can check what the agent asked for.

```python
    async def search(self, query_vector, filters, limit=5):
        self.calls.append(filters)
        query = {"visibility": "shared", "embedding": {"$exists": True}}
        query.update({k: v for k, v in filters.items() if k in FILTER_FIELDS and v is not None})
```

- Applies **the same rules as the real pipeline**: shared only, only allowed filter fields, and no `None` values. If the fake were more generous than the real search, tests could pass while the real thing failed.
- `"embedding": {"$exists": True}` skips answers with no embedding, which the real index would also never return.

```python
        answers = await self.db.answers.find(query).to_list()
        for answer in answers:
            answer["search_score"] = sum(a * b for a, b in zip(query_vector, answer.pop("embedding"), strict=True))
```

- Loads the matching answers, and scores each one. For two vectors of length 1, **cosine similarity is just the sum of the products** of their matching numbers (the "dot product"). `zip` pairs up the numbers; `strict=True` raises an error if the two lists had different lengths, which would mean a bug.
- `answer.pop("embedding")` removes the embedding while using it, just like the real pipeline's `$unset` stage.

```python
        answers.sort(key=lambda a: a["search_score"], reverse=True)
        return answers[:limit]
```

- Sorts from most to least similar, and returns the top `limit`.

### Putting a shared answer straight into the database

```python
def make_shared_answer(
    db, interview_slug, question_order, transcript, visibility="shared", user_sub="someone-else-456"
):
```

- Creates a finished, embedded answer in one line of test code, instead of going through recording, uploading and the worker each time. By default it's **shared** and belongs to **someone else**.

```python
    from bson import ObjectId

    from app.embeddings import build_answer_text

    interview = db.interviews.find_one({"slug": interview_slug})
    question = next(q for q in interview["questions"] if q["order"] == question_order)
```

- Looks up the real question, so the answer has the correct question text and type.

```python
    answer = {
        "attempt_id": ObjectId(),
        "user_sub": user_sub,
        ...
        "recordings": [{"recording_id": "r1", "kind": "main", "status": "uploaded", "transcript": transcript,
                        "video_key": "videos/secret/key.webm"}],
        ...
    }
```

- An answer document shaped exactly like the real ones. `ObjectId()` makes a new random ID. The video key `videos/secret/key.webm` is a recognisable value, so a privacy test can check it never appears in a response.

```python
    answer["search_text"] = build_answer_text(answer)
    answer["embedding"] = word_vector(answer["search_text"])
    return str(db.answers.insert_one(answer).inserted_id)
```

- Adds the search text and a pretend embedding, the same fields the worker would add, saves it, and returns its ID as text.

---

## `tests/test_sharing.py`

**What it proves:** sharing works, is private by default, and only the owner can do it.

```python
def answered_first_question(client, s3):
    attempt_id = start_attempt(client)
    submit_recording(client, s3, attempt_id, 1)
    return attempt_id
```

- Starts an interview and answers question 1. It's a knowledge question, so it counts as answered straight away.

```python
def visibility_of(client, attempt_id, order):
    return client.get(f"/attempts/{attempt_id}").json()["questions"][order - 1]["visibility"]
```

- Reads one question's visibility, the way the review page does. `order - 1` because lists count from 0.

**`test_answers_are_private_by_default`:** answers a question, then checks its visibility is `"private"`.

**`test_an_answer_can_be_shared_and_made_private_again`:**

```python
    assert logged_in_client.put(url, json={"visibility": "shared"}).json() == {"visibility": "shared", "changed": 1}
    assert visibility_of(logged_in_client, attempt_id, 1) == "shared"

    logged_in_client.put(url, json={"visibility": "private"})
    assert visibility_of(logged_in_client, attempt_id, 1) == "private"
```

- Shares it (one answer changed), checks it's shared, then makes it private again and checks that too.

**`test_unanswered_questions_cannot_be_shared`:** trying to share question 2, which hasn't been answered, gets 404.

**`test_only_the_owner_can_share`:** another logged-in user tries to share your answer and gets 404, and the answer stays private.

**`test_share_everything_in_an_interview_at_once`:** answers three questions, calls the whole-interview endpoint, and checks `changed` is 3 and all three are shared.

**`test_only_private_or_shared_are_allowed`:** sending `"public"` gets 422, rejected by the `Visibility` type before our code runs.

---

## `tests/test_community.py`

**What it proves:** the Community endpoints only ever show shared answers, never reveal who gave them, and the search endpoint applies its limits.

```python
LANGSMITH = "I traced every retrieval step of our RAG pipeline in LangSmith to see which documents were used."
DOCKER = "I would use a slim base image and run the container as a non-root user."
```

- Two sample transcripts on clearly different topics, reused across tests.

**`test_only_shared_answers_are_listed`:** creates one shared and one private answer; the list contains only the shared one.

**`test_answers_can_be_filtered_by_interview_and_question`:**

```python
    wanted = make_shared_answer(db, "agentic-ai", 3, LANGSMITH)
    make_shared_answer(db, "agentic-ai", 1, "about workflows")
    make_shared_answer(db, "devops-docker", 3, DOCKER)

    answers = logged_in_client.get("/community/answers", params={"interview_slug": "agentic-ai", "question_order": 3})
```

- Three answers: the right interview and question, the right interview but wrong question, and the right question but wrong interview. Only the first comes back. `params=` builds the `?interview_slug=...&question_order=...` part of the address.

**`test_shared_answers_never_reveal_who_gave_them`:**

```python
    text = json.dumps(detail)
    assert "someone-else-456" not in text
    assert "videos/secret/key.webm" not in text
    assert "embedding" not in detail
```

- Turns the whole response into text and checks the owner's ID and the video's location appear **nowhere** in it, and that the embedding isn't included. Checking the whole text catches a leak in any field, including ones added in future.

**`test_your_own_shared_answers_are_marked_as_yours`:** an answer owned by the test user (`test-user-123`) comes back with `is_mine` set to true.

**`test_a_private_answer_looks_exactly_like_a_missing_one`:** a private answer, a made-up ID and a badly formed ID all get the same 404.

**`test_community_pages_need_login`:** without logging in, the list gets 401.

### The search endpoint

```python
class StubAgent:
    def __init__(self, answers):
        self.answers = answers
        self.questions = []

    async def run(self, question):
        self.questions.append(question)
        return {"reply": "Here's what I found.", "answers": self.answers}
```

- A stand-in for the search agent, with the same `run` method. It records the questions it's asked and returns whatever it was given. The real agent has its own tests (below), so these tests focus on what the **endpoint** does.

**`test_search_returns_the_agents_reply_and_answers`:**

```python
    logged_in_client.app.dependency_overrides[get_search_agent] = lambda: agent
```

- Replaces the real `get_search_agent` dependency with one returning the stub, the same technique the tests have used since Phase 1. Then it checks the reply and answer cards come back, and the agent received the question.

**`test_search_is_unavailable_when_switched_off`:** with no agent, the endpoint answers 503.

**`test_searches_are_limited_per_hour`:**

```python
    logged_in_client.app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"searches_per_hour": 2}
    )

    codes = [logged_in_client.post("/community/search", json={"question": "testing"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
```

- Swaps in settings with a limit of 2 (`model_copy(update=...)` makes a copy with one value changed), searches three times, and checks the third is refused with 429.

**`test_empty_questions_are_rejected`:** an empty question gets 422 from `SearchRequest`'s minimum length.

---

## `tests/test_search_agent.py`

**What it proves:** the agent's loop works, and its guardrails hold, whatever Claude does.

### A scripted Claude

```python
def tool_use(name, tool_input, call_id="call-1"):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=tool_input)


def text(value):
    return SimpleNamespace(type="text", text=value)
```

- Build pretend pieces of a Claude reply. `SimpleNamespace` makes a quick object with whatever attributes you give it, here matching the shape of the Anthropic library's blocks.

```python
class ScriptedClaude:
    def __init__(self, moves):
        self.moves = list(moves)
        self.requests = []
        self.messages = SimpleNamespace(create=self.create)
```

- A pretend Anthropic client, given a list of "moves" to play back in order. `self.messages = SimpleNamespace(create=...)` makes `client.messages.create(...)` work, just like the real client.

```python
    async def create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return SimpleNamespace(content=self.moves.pop(0))
```

- Records each request, saving a **copy** of the conversation (the agent keeps adding to the same list, so without a copy every saved request would show the final conversation). Then it returns the next scripted move.

```python
    def tool_output(self, request_number):
        last_message = self.requests[request_number]["messages"][-1]
        return json.loads(last_message["content"][0]["content"])
```

- Reads what our tool sent back to Claude. After a tool runs, its result is the last message of the *next* request, so `tool_output(1)` reads the result of the tool called in the first move.

### Running async tests

```python
@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- The agent is `async`, so its tests are too. `@pytest.mark.anyio` on each test (from the `anyio` library, which comes with FastAPI) runs them, and this fixture tells it to use Python's standard `asyncio`.

```python
@pytest.fixture
async def async_db():
    client = AsyncMongoClient(os.environ["MONGODB_URI"])
    db = client["mock_interview_test"]
    await seed_interviews(db)
    yield db
    await client.close()
```

- The agent needs the **async** database client, like the API uses. `seed_interviews` makes sure the five interviews exist, since `list_interviews` reads them.

```python
def make_agent(async_db, moves, settings=None):
    claude = ScriptedClaude(moves)
    settings = settings or get_settings()
    search = InMemoryAnswerSearch(async_db, settings)
    agent = SearchAgent(async_db, search, FakeEmbedder(), settings, client=claude)
    return agent, claude, search
```

- Builds a **real** `SearchAgent` with the fakes plugged in, and returns all three, so tests can check what each one saw.

**`test_the_agent_decomposes_the_question_and_finds_the_answer`:** plays out the example from chapter 05:

```python
    agent, claude, search = make_agent(async_db, [
        [tool_use("list_interviews", {})],
        [tool_use("search_answers", {"query": "observing a RAG pipeline with LangSmith",
                                     "interview_slug": "agentic-ai", "question_order": 3})],
        [tool_use("submit_answer", {"answer": "One answer mentions LangSmith.", "answer_ids": [langsmith_id]})],
    ])
```

- Three moves: list the interviews, search with filters, submit. Then it checks:
  - the reply and the chosen answer came back,
  - `search.calls == [{"interview_slug": "agentic-ai", "question_order": 3}]`: the precise part became filters,
  - `"key_points" not in json.dumps(interviews_seen)`: the private rubrics never reached Claude.

**`test_search_results_rank_by_meaning`:** with a Docker answer and a LangSmith answer, a search for "LangSmith RAG pipeline" returns the LangSmith answer first, with a higher relevance and an excerpt mentioning LangSmith.

**`test_private_answers_are_never_found`:** a private answer that matches perfectly still isn't returned: the search result is an empty list.

**`test_made_up_answer_ids_are_thrown_away`:**

```python
        [tool_use("submit_answer", {"answer": "x", "answer_ids": [real_id, never_found, "invented", real_id]})],
```

- The agent cites a real search result, a real answer it never searched for, an invented ID, and the real one again. Only the real search result survives, once: `finish` keeps only IDs in `seen`, without duplicates.

**`test_the_agent_stops_after_the_step_limit`:** a "confused" Claude that searches forever. With a limit of 3, it's called exactly 3 times, and the agent returns the honest fallback message, plus the answer it did find.

**`test_a_plain_text_reply_still_finishes`:** if Claude replies in plain text instead of calling `submit_answer`, that text becomes the reply, with no answers.

**`test_bad_filters_are_ignored_not_passed_on`:** a question number of 99 and an unknown question type are dropped, so the search receives no filters at all (`[{}]`).

---

## `tests/test_embeddings.py`

**What it proves:** the right text is embedded, Voyage is called correctly, the worker embeds at the right moments without risking scores, and the vector search pipeline and index are built correctly.

**`test_answer_text_includes_the_question_and_answered_follow_ups`:** builds an answer with one answered and one unanswered follow-up, and checks the exact text, which includes the answered follow-up and leaves out the other.

### Calling Voyage with a pretend network

```python
    def pretend_voyage(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.2], "index": 1}, {"embedding": [0.1], "index": 0}]})

    settings = get_settings().model_copy(update={"voyage_api_key": SecretStr("secret-key")})
    embedder = VoyageEmbedder(settings, transport=httpx.MockTransport(pretend_voyage))
```

- `httpx.MockTransport` sends every request to the function given, instead of the internet. Here, `pretend_voyage` records the request and replies like Voyage would, but **out of order**, to prove our code sorts by `index`.
- The key must be passed as `SecretStr("...")`, because `model_copy(update=...)` skips Pydantic's usual conversion.

```python
    assert embedder.embed_documents(["first", "second"]) == [[0.1], [0.2]]
```

- The embeddings come back in the right order.

```python
    assert str(request.url) == VOYAGE_URL
    assert request.headers["Authorization"] == "Bearer secret-key"
    assert json.loads(request.content) == {
        "input": ["first", "second"],
        "model": "voyage-4-lite",
        "input_type": "document",
        "output_dimension": 1024,
    }
```

- Checks the request went to the right address, with the key in the right header, and the exact body.

**`test_queries_are_embedded_as_queries`:** `embed_query` sends `input_type: "query"`.

**`test_a_voyage_error_becomes_an_exception`:** a 401 reply raises `httpx.HTTPStatusError`, rather than failing later in a confusing way.

**`test_the_key_is_hidden_when_settings_are_printed`:** `repr(settings)` (what Python prints for an object) doesn't contain the key, because it's a `SecretStr`.

### The worker's embedding step

**`test_finished_knowledge_answers_are_embedded`:** answers question 1, runs the worker with a `FakeEmbedder`, and checks the answer now has a 1024-number embedding and a `search_text`, and that exactly that text was embedded.

**`test_situational_answers_are_embedded_only_once_accepted`:**

```python
    missing_result = {"situation": "clear", "task": "clear", "action": "clear", "result": "missing"}
    worker = make_worker_context(db, scorer=FakeScorer(star_ratings=[missing_result, ALL_CLEAR]))
```

- A pretend Claude that asks one follow-up on question 4, then accepts. After the main answer, question 4 has **no** embedding, because it isn't finished. After the follow-up is answered and accepted, it does, and its `search_text` includes the follow-up.

**`test_an_embedding_failure_does_not_fail_the_job`:** with an embedder that always fails, the job still succeeds: the answer is `done` and still has its score of 75, but no embedding. This proves search problems can't cost a candidate their results.

**`test_backfill_embeds_only_what_is_missing`:** two answers processed without an embedder (like before Phase 5), then `backfill` embeds both (returns 2), and running it again embeds nothing (returns 0).

### The pipeline and the index

**`test_the_pipeline_always_filters_to_shared_answers`:**

```python
    pipeline = build_search_pipeline(
        [0.1], {"question_order": 3, "interview_slug": None, "user_sub": "sneaky"}, 5, "answer_embeddings"
    )
```

- Passes a real filter, an empty one (`None`) and a sneaky one (`user_sub`, not an allowed filter). The resulting filter is exactly "shared AND question 3", with `numCandidates` 20 times the limit, plus the score and `$unset` stages.

```python
class FakeAnswers:
    def __init__(self, existing=(), unsupported=False):
        self.existing, self.unsupported, self.created = list(existing), unsupported, []
```

- A pretend `answers` collection for testing `ensure_vector_index`: it can pretend an index already exists, or that search indexes aren't supported, and it records any index it's asked to create. `FakeCursor` and `FakeDb` complete the pretend database.

**`test_the_vector_index_is_created_when_missing`:** creates exactly one index, with the right name, the `vectorSearch` type, and the right vector field (1024 dimensions, cosine).

**`test_an_existing_index_is_left_alone`:** if it already exists, nothing is created.

**`test_without_vector_search_the_app_carries_on`:** if search indexes aren't supported, `ensure_vector_index` returns `False` instead of crashing.
