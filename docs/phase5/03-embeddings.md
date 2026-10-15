# 03 Embeddings

An **embedding** is a list of numbers (1024 here) that captures what a piece of text *means*. Texts with similar meanings get similar lists, even when they use different words, which is what lets a search for "monitoring a RAG pipeline" find an answer about "tracing retrieval steps in LangSmith".

Two kinds of text get embedded:

- **Documents:** each finished answer, embedded by the **worker** (this chapter).
- **Queries:** each search, embedded by the **search agent** in the API (chapter 05).

---

## `backend/app/embeddings.py`

**Where and when it's used:** `build_answer_text` and `VoyageEmbedder.embed_documents` run in the worker after an answer is finished, and in the backfill script. `VoyageEmbedder.embed_query` runs in the API for every search.

### Imports and the address

```python
from typing import Protocol

import httpx

from app.config import Settings

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
```

- `Protocol` describes "anything with these methods", so the real Voyage class and the tests' fake both fit.
- `httpx` is the HTTP library already used in `auth.py`.
- `VOYAGE_URL` is Voyage's embeddings endpoint, kept in a constant so the tests can check requests go there.

### `build_answer_text`: what represents an answer in search

```python
def build_answer_text(answer: dict) -> str:
```

- Takes an answer document from MongoDB and returns one piece of text. It's called by `embed_answer` (below).

```python
    transcripts = {r["recording_id"]: r.get("transcript") or "" for r in answer["recordings"]}
```

- A **dictionary comprehension**: it builds a lookup from each recording's ID to its transcript, so follow-up transcripts can be found by ID.
- `r.get("transcript") or ""` uses an empty string if a transcript is missing or empty, so the code never handles `None`.

```python
    main = next((r for r in answer["recordings"] if r["kind"] == "main"), {})
```

- Finds the main recording (the original answer). `next(..., {})` returns the first match, or an empty dictionary if there isn't one, instead of crashing.

```python
    parts = [f"Question: {answer['question_text']}", f"Answer: {main.get('transcript') or ''}"]
```

- Starts the list of lines with the question and the main answer. Including the **question** matters: an answer that just says "I'd use an index" only makes sense next to its question.

```python
    for follow_up in sorted(answer.get("follow_ups", []), key=lambda f: f["number"]):
        if follow_up.get("recording_id"):
            parts.append(f"Follow-up question: {follow_up['question']}")
            parts.append(f"Answer: {transcripts.get(follow_up['recording_id'], '')}")
```

- Adds each follow-up question and its answer, in order (`sorted` by `number`). Only follow-ups that were actually answered (they have a `recording_id`) are included.
- This matters because the detail someone searches for is often in a follow-up answer.

```python
    return "\n".join(parts)
```

- Joins the lines into one text, with a line break (`\n`) between each.

The result looks like this:

```
Question: Tell me about a time...
Answer: We fixed a slow API.
Follow-up question: What did you do?
Answer: I added an index.
```

### The two Protocols

```python
class DocumentEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class QueryEmbedder(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
```

- These describe what the worker needs (`embed_documents`) and what the API needs (`embed_query`). The `...` means "no code here: this only describes the shape".
- `list[list[float]]` means "a list of embeddings, each a list of decimal numbers".

### `VoyageEmbedder`

```python
class VoyageEmbedder:
```

- The real implementation. It sends ordinary HTTP POST requests to Voyage, rather than using Voyage's own library, so you can see exactly what's sent.

```python
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None):
```

- Runs when a `VoyageEmbedder` is created: once in the worker, once in the API, and once in the backfill script.
- `transport` is only ever passed by **tests**. An httpx "transport" is the part that actually sends requests over the network; tests swap in a pretend one that records requests instead of sending them. `None` means "use the real network".

```python
        self.transport = transport
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
```

- Stores the transport, the model name (`voyage-4-lite`) and the number of dimensions (1024) for later.

```python
        self.headers = {"Authorization": f"Bearer {settings.voyage_api_key.get_secret_value()}"}
```

- Builds the login header Voyage expects: `Authorization: Bearer <your key>`, the same style used for Cognito tokens.
- `.get_secret_value()` is the only way to read a `SecretStr`. It's done once, here, so it's easy to see where the key is used.

```python
    def _body(self, texts: list[str], input_type: str) -> dict:
        return {
            "input": texts,
            "model": self.model,
            "input_type": input_type,        # "document" or "query"
            "output_dimension": self.dimensions,
        }
```

- Builds the JSON body for a request. The leading `_` in the name is a Python convention meaning "for use inside this class".
- `input`: the list of texts to embed.
- `input_type`: tells Voyage whether these are documents being stored or a query being searched with. Voyage adds a short instruction for each type before embedding, which makes searches more accurate.
- `output_dimension`: ask for exactly 1024 numbers, to match the vector index.

```python
    @staticmethod
    def _vectors(response: httpx.Response) -> list[list[float]]:
```

- Reads the embeddings out of Voyage's reply. `@staticmethod` means it doesn't need `self`: it only works on the response it's given.

```python
        response.raise_for_status()
```

- If Voyage replied with an error, for example 401 for a wrong key or 429 for too many requests, this raises an exception straight away, instead of failing later with a confusing error.

```python
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]
```

- Voyage replies with `{"data": [{"embedding": [...], "index": 0}, ...]}`. `index` says which input text each embedding belongs to. Sorting by it guarantees the embeddings come back in the same order as the texts, even if the list were ever out of order.
- The last line keeps only the lists of numbers.

```python
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=30, transport=self.transport) as client:
            response = client.post(VOYAGE_URL, headers=self.headers, json=self._body(texts, "document"))
        return self._vectors(response)
```

- The **worker's** version. It's ordinary blocking code, because the worker does one job at a time.
- `with httpx.Client(...) as client:` opens a connection and closes it automatically afterwards. `timeout=30` gives up after 30 seconds rather than hanging forever.
- `json=...` sends the body as JSON, with `input_type` set to `"document"`.

```python
    async def embed_query(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            response = await client.post(VOYAGE_URL, headers=self.headers, json=self._body([text], "query"))
        return self._vectors(response)[0]
```

- The **API's** version, which is `async` so the web server can handle other requests while it waits for Voyage.
- It sends one text as a one-item list, with `input_type` set to `"query"`, and returns the single embedding (`[0]`).

---

## `backend/app/processing.py`: embedding finished answers

**Where and when it's used:** at the end of `process_recording`, which the worker runs for every job.

### The worker's toolbox gains an embedder

```python
from app.embeddings import DocumentEmbedder, build_answer_text
```

```python
    # Phase 5: makes embeddings for search. None means search is switched off.
    embedder: DocumentEmbedder | None = None
```

- Added to `WorkerContext`, the toolbox from Phase 3. `= None` gives it a default, so code that builds a `WorkerContext` without an embedder (like the older tests) still works. A field with a default must come after the fields without one, which is why it's last.

### The new step at the end of `process_recording`

```python
    # --- 5: make it searchable (Phase 5) -------------------------------------
    if embed_answer(ctx.db, ctx.embedder, ctx.settings, answer_id):
        outcome += ", embedded for search"
    return outcome
```

- Runs **after** the answer is marked `done`, so the candidate's results appear without waiting for the embedding.
- If embedding worked, it adds a note to the outcome, which appears in the worker's log, like `scored knowledge answer, embedded for search`.

### `embed_answer`

```python
def embed_answer(db: Database, embedder: DocumentEmbedder | None, settings: Settings, answer_id: ObjectId) -> bool:
```

- Takes just the three things it needs, instead of the whole `WorkerContext`, so the backfill script (below) can use it without loading Whisper. It returns `True` if the answer was embedded.

```python
    if embedder is None:
        return False
```

- No embedder means no Voyage key was set, so search is switched off: do nothing.

```python
    answer = db.answers.find_one({"_id": answer_id})
    if answer is None or answer["status"] != "answered":
        return False
```

- Loads the answer fresh from the database, with all the latest transcripts.
- Only **finished** answers are embedded. A situational answer waiting for a follow-up (`awaiting_follow_up`) is skipped; it gets embedded when it's finally accepted, so the embedding includes the follow-up answers too.

```python
    text = build_answer_text(answer)
```

- Builds the text described above.

```python
    try:
        [vector] = embedder.embed_documents([text])
```

- Sends one text and receives one embedding. `[vector] = ...` unpacks a one-item list into the variable `vector`, and raises an error if the list doesn't have exactly one item, which is a free check.

```python
    except Exception:
        logger.exception("Couldn't embed answer %s for search", answer_id)
        return False
```

- If Voyage fails, log the full error and carry on. **This is deliberate.** If the error were allowed to escape, the whole job would fail and be retried, and after three tries the answer would be marked "failed", so the candidate could lose their score over a search feature. Search is a bonus; the backfill script can embed this answer later.

```python
    db.answers.update_one(
        {"_id": answer_id},
        {"$set": {
            "embedding": vector,
            "search_text": text,
            "embedding_model": settings.embedding_model,
            "embedded_at": datetime.now(UTC),
        }},
    )
    return True
```

- Saves four fields on the answer:
  - `embedding`: the 1024 numbers, which the vector index searches.
  - `search_text`: the exact text that was embedded. The search agent shows excerpts from it.
  - `embedding_model`: which model made it. If you ever change models, you'll know which answers need re-embedding, since embeddings from different models can't be compared.
  - `embedded_at`: when, for reference.

**Every** finished answer is embedded, shared or not. That way, ticking "Share" makes an answer searchable instantly, with no extra work. Private answers are still never returned, because every search filters on `visibility = "shared"` (chapter 04).

---

## `backend/app/worker.py`

**Where and when it's used:** once, when the worker program starts.

```python
from app.embeddings import VoyageEmbedder
```

```python
def make_embedder(settings):
    if not settings.voyage_api_key.get_secret_value():
        logger.warning("VOYAGE_API_KEY is not set - answers won't be made searchable")
        return None
    return VoyageEmbedder(settings)
```

- Creates the embedder if a Voyage key is set. If not, it logs a warning and returns `None`.
- Compare with the Anthropic key: a missing Anthropic key **stops** the worker (from Phase 3), because scoring is essential. A missing Voyage key only **warns**, because search is optional.

```python
        embedder=make_embedder(settings),
```

- Added where `WorkerContext` is created in `main()`, putting the embedder (or `None`) into the toolbox.

---

## `backend/app/backfill_embeddings.py`

**Where and when it's used:** run by hand, once, after setting up Phase 5:

```
docker compose exec worker python -m app.backfill_embeddings
```

It embeds answers finished **before** Phase 5, and any whose embedding failed. "Backfill" means filling in data that's missing from the past.

```python
import logging

from pymongo import MongoClient

from app.config import get_settings
from app.embeddings import VoyageEmbedder
from app.processing import embed_answer
```

- The ordinary (non-async) MongoDB client, like the worker uses, and the same `embed_answer` the worker uses, so a backfilled answer is embedded exactly like a new one.

```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_interview.backfill")
```

- Turns on log messages, so you see the summary when it runs.

```python
def backfill(db, embedder, settings) -> int:
    missing = db.answers.find({"status": "answered", "embedding": {"$exists": False}}, {"_id": 1}).to_list()
```

- Finds finished answers that have **no** `embedding` field. `{"$exists": False}` matches documents where the field doesn't exist at all.
- `{"_id": 1}` is a projection: only load each answer's ID, since `embed_answer` loads the full answer itself.

```python
    embedded = sum(embed_answer(db, embedder, settings, answer["_id"]) for answer in missing)
```

- Embeds each one. `embed_answer` returns `True` or `False`, and in Python `sum` counts `True` as 1 and `False` as 0, so this counts how many worked.

```python
    logger.info("Embedded %s of %s answers that were missing embeddings", embedded, len(missing))
    return embedded
```

- Reports the result, and returns the count (which the tests check).

Running it twice is safe: the second time, nothing is missing, so nothing happens. That property is called being **idempotent**, as in earlier phases.

```python
def main() -> None:
    settings = get_settings()
    if not settings.voyage_api_key.get_secret_value():
        raise SystemExit("VOYAGE_API_KEY is not set")
    db = MongoClient(settings.mongodb_uri)[settings.mongodb_db_name]
    backfill(db, VoyageEmbedder(settings), settings)


if __name__ == "__main__":
    main()
```

- `main` connects to the database and runs the backfill. Without a key it stops with a clear message (`SystemExit` ends the program and prints the message).
- `if __name__ == "__main__":` means "only run `main()` when this file is run as a program", not when the tests import it. That's why the tests can call `backfill(...)` with fakes.
