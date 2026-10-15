# 01 Settings and startup

This chapter covers the pieces everything else depends on: the new settings, the packages, the Docker setup, the database indexes, and the code that decides at startup whether search can be switched on.

---

## `backend/app/config.py`: the new settings

**Where and when it's used:** `Settings` is read once when any program starts (the API, the worker, the backfill script, the tests), through `get_settings()`. Every file below reads its Phase 5 values from here.

### The import

```python
from pydantic import SecretStr
```

- Brings in `SecretStr`, a Pydantic type for secret text. It's used for the Voyage key below.

### The settings block

```python
    # --- Sharing and search (Phase 5) ---------------------------------------
    voyage_api_key: SecretStr = SecretStr("")
```

- `voyage_api_key` is filled from the `VOYAGE_API_KEY` environment variable (pydantic-settings matches the name in capitals, as explained in earlier phases).
- `: SecretStr` makes it a *secret* string. If anything prints the settings, for example in an error message or a log, it shows `**********` instead of the key.
- `= SecretStr("")` is the default: an empty secret, meaning "no key set".
- **Why our code needs this key when it didn't need `AWS_SECRET_ACCESS_KEY` or `ANTHROPIC_API_KEY`:** boto3 and the anthropic library read their keys from the environment by themselves. For Voyage, we write the HTTP request ourselves (chapter 03), so our code has to put the key into it.

```python
    embedding_model: str = "voyage-4-lite"
```

- Which Voyage model makes the embeddings. `voyage-4-lite` is the cheapest current one, and it's covered by Voyage's free allowance of 200 million tokens per account.

```python
    embedding_dimensions: int = 1024
```

- How many numbers are in each embedding. Voyage's current models can produce 256, 512, 1024 or 2048; 1024 is their default. The **same number** must be used in three places: when embedding answers, when embedding queries, and in the vector index (chapter 04). Keeping it in one setting guarantees they match.

```python
    vector_index_name: str = "answer_embeddings"
```

- The name of the vector search index. It's used when creating the index and when searching with it, so it lives in one place.

```python
    create_vector_index: bool = True
```

- Whether the API should create the vector index at startup if it's missing. It's `True` normally. The tests set `CREATE_VECTOR_INDEX=false`, because they use a pretend search (chapter 08) and shouldn't build a real index on your test database each time.

```python
    search_agent_model: str = "claude-haiku-4-5-20251001"
    search_agent_max_steps: int = 6
```

- The Claude model the search agent uses, and the most times it may go round its think-act-observe loop. The step limit is a guardrail: a confused agent stops after 6 steps instead of running (and costing money) forever.

```python
    searches_per_hour: int = 30
```

- How many searches one person may run per hour. Each search costs a little (a Claude call or two, plus Voyage), so this is a **cost guardrail**. It's checked in `routers/community.py` (chapter 06).

---

## `backend/requirements.txt` and `requirements-worker.txt`

**Where and when it's used:** when Docker builds the images, and when you run `pip install -r requirements-dev.txt` for tests.

```
# Phase 5: the API runs the search agent, so it needs Claude too.
anthropic==1.11.0
```

- Added to `requirements.txt` (the API's packages). Until now only the worker used Claude, so `anthropic` lived in `requirements-worker.txt`. Now the API's search agent calls Claude too, so it moved here.
- It was **removed** from `requirements-worker.txt`. The worker still gets it, because that file starts with `-r requirements.txt`, which means "include everything in requirements.txt too".
- No package was added for Voyage: we call its API with `httpx`, which was already installed.

---

## `backend/.env.example`

**Where and when it's used:** a template you copy into your real `backend/.env`. Docker Compose reads `.env` when it starts the backend and worker.

```
MONGODB_URI=mongodb://localhost:27017/?directConnection=true
```

- The database address for running **tests on your laptop**. `?directConnection=true` was added because the new database image (below) runs as a one-member *replica set*, and this tells the driver to talk to that single member directly instead of trying to discover others.

```
VOYAGE_API_KEY=
```

- Where your Voyage key goes. Like every other key, it's a secret, and `.env` is ignored by Git.

---

## `docker-compose.yml`: the database with vector search

**Where and when it's used:** when you run `docker compose up`.

```yaml
  mongo:
    image: mongodb/mongodb-atlas-local:8.0
```

- Replaces `image: mongo:8`. **Atlas Local** is MongoDB's own development image: the same database plus the search engine behind Atlas Search and Vector Search, running on your laptop. Plain `mongo:8` has no vector search.
- `:8.0` pins the version, so everyone gets the same database.

```yaml
    hostname: mongo
```

- Gives the container a fixed network name, `mongo`, matching the address the backend and worker connect to (`mongodb://mongo:27017`). MongoDB's own Docker Compose examples for this image set a hostname too.

```yaml
    ports:
      - "127.0.0.1:27017:27017"
```

- Unchanged: the database is only reachable from your own computer.

```yaml
    volumes:
      - atlas-data:/data/db
      - atlas-config:/data/configdb
```

- Two Docker volumes keep the data between restarts: `/data/db` holds the data, and `/data/configdb` holds the replica-set configuration this image needs.
- They have **new names** on purpose. Your old volume was written by MongoDB 8.3, and this image is 8.0; an older version can't safely open data files made by a newer one. So you start with a fresh, empty dev database, which is fine for development data.
- The old `healthcheck:` block was **removed**: this image has its own built-in health check, and `depends_on: condition: service_healthy` (in the backend and worker) uses it automatically.

```yaml
      MONGODB_URI: mongodb://mongo:27017/?directConnection=true
```

- In both the `backend` and `worker` services, the address gained `?directConnection=true`, for the replica-set reason above.

```yaml
volumes:
  atlas-data:
  atlas-config:
  whisper-models:
```

- Declares the volumes used above. `mongo-data` was removed, since nothing uses it anymore (Docker keeps the old volume itself until you delete it).

---

## `backend/app/db.py`: two new indexes

**Where and when it's used:** `create_indexes()` runs once every time the API starts, from `lifespan` in `main.py`. Creating an index that already exists does nothing.

```python
    await db.answers.create_index([("visibility", ASCENDING), ("answered_at", DESCENDING)])
```

- The Community page asks "shared answers, newest first". This index lists answers by `visibility`, then by `answered_at` from newest to oldest, so MongoDB can answer that without scanning every answer.

```python
    await db.search_log.create_index([("user_sub", ASCENDING), ("created_at", DESCENDING)])
```

- The search limit counts "this user's searches since an hour ago". This index makes that count fast. `search_log` is a new collection, filled in chapter 06.

```python
    await db.search_log.create_index("created_at", expireAfterSeconds=7 * 24 * 60 * 60, name="search_log_ttl")
```

- A **TTL ("time to live") index**. `expireAfterSeconds` tells MongoDB to delete each document by itself once its `created_at` is that many seconds old: 7 days × 24 hours × 60 minutes × 60 seconds = 604,800 seconds.
- Why: the log is only needed for the hourly limit, so old entries are useless, and keeping people's search questions forever would be bad privacy practice. MongoDB cleans up automatically, with no extra code.
- `name="search_log_ttl"` gives it a clear name, since `search_log` now has two indexes involving `created_at`.

---

## `backend/app/main.py`: switching search on at startup

**Where and when it's used:** `lifespan` runs once when the API starts. It now calls `set_up_search`, which decides whether the search feature is available.

### New imports

```python
import os
```

- Used to check whether `ANTHROPIC_API_KEY` is set.

```python
from app.config import Settings, get_settings
from app.embeddings import VoyageEmbedder
from app.routers import attempts, community, health, interviews, live, users
from app.search_agent import SearchAgent
from app.vector_search import AnswerSearch, ensure_vector_index
```

- `Settings` is now imported for the type hint in `set_up_search`.
- `VoyageEmbedder` (chapter 03), `SearchAgent` (chapter 05), `AnswerSearch` and `ensure_vector_index` (chapter 04) are the pieces search is built from.
- `community` is the new router (chapter 06).

### The call inside `lifespan`

```python
    await set_up_search(app, db, settings)
```

- Runs after the database, storage and queue are set up, and before the app starts taking requests.

### The function

```python
async def set_up_search(app: FastAPI, db, settings: Settings) -> None:
```

- `async` because it talks to the database. It returns nothing; its job is to store objects on `app.state`.

```python
    available = await ensure_vector_index(db, settings) if settings.create_vector_index else False
```

- If index creation is switched on, call `ensure_vector_index` (chapter 04), which creates the index if needed and returns `True` if vector search works on this database. If it's switched off (in tests), treat vector search as unavailable.
- `X if condition else Y` is Python's one-line "if": it means "X when the condition is true, otherwise Y".

```python
    app.state.answer_search = AnswerSearch(db, settings, available)
    app.state.search_agent = None
```

- Creates the object that runs vector searches and stores it on `app.state`, the app's shared storage.
- Starts by assuming there's no agent. It's only replaced if everything needed is present.

```python
    missing = []
    if not available:
        missing.append("vector search")
    if not settings.voyage_api_key.get_secret_value():
        missing.append("VOYAGE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
```

- Builds a list of whatever is missing. Search needs all three: vector search in the database, a Voyage key to embed queries, and an Anthropic key for the agent.
- `get_secret_value()` is the only way to read the text inside a `SecretStr`. An empty string counts as "not set".
- `os.environ.get(...)` returns `None` if the variable doesn't exist, which also counts as "not set".

```python
    if missing:
        logger.warning("Search is switched off - missing: %s", ", ".join(missing))
        return
```

- If anything is missing, log one clear warning naming all of it, and stop here, leaving `search_agent` as `None`. The rest of the app works normally; only the search endpoint answers "not available".
- This follows the same rule as earlier phases: a missing optional feature shouldn't stop the app from starting.

```python
    app.state.search_agent = SearchAgent(db, app.state.answer_search, VoyageEmbedder(settings), settings)
```

- Everything is present, so build the agent and store it. It's handed the database, the search object and a Voyage embedder: dependency injection again, so tests can hand it fakes instead.

### Registering the router

```python
    app.include_router(community.router)
```

- In `create_app`, this adds the Community endpoints (chapter 06) to the app.
