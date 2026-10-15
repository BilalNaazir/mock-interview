# 04 Vector search

Once every finished answer has an `embedding`, finding answers "about" something means finding the embeddings **closest** to the query's embedding. Comparing a query against every answer one by one would get slow as the number of answers grows, so MongoDB builds a **vector search index** that finds the closest ones quickly.

---

## `backend/app/vector_search.py`

**Where and when it's used:**

- `ensure_vector_index` runs **once at API startup**, from `set_up_search` in `main.py` (chapter 01).
- `AnswerSearch.search` runs **every time the search agent searches** (chapter 05), which can be several times per question.

### Imports

```python
import logging

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.operations import SearchIndexModel

from app.config import Settings
```

- `CollectionInvalid` is the error raised when creating a collection that already exists.
- `OperationFailure` is the general error MongoDB returns when it can't do something, such as vector search on a database that doesn't support it.
- `SearchIndexModel` describes a search index to create.

```python
logger = logging.getLogger("mock_interview.vector_search")
```

- A named logger, so messages from this file are labelled `mock_interview.vector_search` in the logs.

### Which fields can be filtered on

```python
FILTER_FIELDS = ("visibility", "interview_slug", "question_order", "question_type")
```

- A vector search can be narrowed down, for example "only question 3 of the Agentic AI interview". MongoDB only allows filtering on fields that are declared in the index as `filter` fields, so this tuple lists them in one place. It's used both when creating the index and when building a search, so the two can't disagree.
- A tuple (round brackets) is like a list that can't be changed, which suits a fixed list like this.

### The index definition

```python
def vector_index_definition(settings: Settings) -> dict:
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": settings.embedding_dimensions,
                "similarity": "cosine",
            },
```

- Describes the index to MongoDB:
  - `"type": "vector"`: this field holds embeddings.
  - `"path": "embedding"`: the field's name on each answer.
  - `"numDimensions"`: how many numbers each embedding has (1024). It must match what Voyage produces, or nothing could be compared.
  - `"similarity": "cosine"`: how "closeness" is measured. **Cosine similarity** compares the *direction* two lists of numbers point in, which is the standard way to compare text embeddings.

```python
            *({"type": "filter", "path": field} for field in FILTER_FIELDS),
        ]
    }
```

- Adds one `{"type": "filter", "path": ...}` entry for each field in `FILTER_FIELDS`.
- The `*` "unpacks" the generated entries into the surrounding list, so the result is one flat list of five entries: the vector field and the four filter fields.

### Creating the index at startup

```python
async def ensure_vector_index(db: AsyncDatabase, settings: Settings) -> bool:
```

- Makes sure the index exists, and returns `True` if vector search is available on this database, or `False` if it isn't.

```python
    try:
        try:
            await db.create_collection("answers")
        except CollectionInvalid:
            pass  # it already exists - the usual case
```

- A search index can only be put on a collection that exists. On a brand-new database (before anyone has answered anything), `answers` doesn't exist yet, so this creates it.
- Normally it already exists, and `create_collection` raises `CollectionInvalid`; `pass` means "do nothing", so that's simply ignored.

```python
        cursor = await db.answers.list_search_indexes(settings.vector_index_name)
        if not await cursor.to_list():
```

- Asks MongoDB for any search index with our index's name. With PyMongo's async client, `list_search_indexes` returns a **cursor** (a way of reading results bit by bit), and `to_list()` reads them all into a list.
- `if not ...` is true when the list is empty, meaning the index doesn't exist yet.

```python
            await db.answers.create_search_index(
                SearchIndexModel(
                    definition=vector_index_definition(settings),
                    name=settings.vector_index_name,
                    type="vectorSearch",
                )
            )
            logger.info("Created vector search index '%s'", settings.vector_index_name)
```

- Creates the index with the definition above. `type="vectorSearch"` tells MongoDB it's a vector index (rather than a text search index).
- MongoDB builds it **in the background**, usually within seconds on a small collection, so this returns straight away.
- Checking first means this only happens once: on every later startup, the index exists, and nothing is created.

```python
        return True
```

- Vector search works here.

```python
    except OperationFailure as error:
        logger.warning("Vector search is unavailable on this database (%s) - search is switched off", error)
        return False
```

- On a database without vector search, such as plain `mongo:8` (which GitHub Actions uses for tests), these commands fail with `OperationFailure`. Instead of crashing the whole app, log a warning and report "not available". The rest of the app runs normally, and only search is switched off.

### Building a search

```python
def build_search_pipeline(query_vector: list[float], filters: dict, limit: int, index_name: str) -> list[dict]:
```

- Builds the **aggregation pipeline** for one search. A pipeline is a list of steps ("stages") MongoDB runs in order, each passing its results to the next. It's a separate function so tests can check exactly what it builds without a database.

```python
    conditions = [{"visibility": "shared"}]
```

- **The most important line in this file.** Every search starts with "only shared answers". It's added here, in code, whatever filters the caller passes, so a private answer can never be returned by a search, even if the agent (or a bug) asked for something odd.

```python
    conditions += [{field: value} for field, value in filters.items() if field in FILTER_FIELDS and value is not None]
```

- Adds one condition per filter passed in, like `{"question_order": 3}`, but only:
  - for fields in `FILTER_FIELDS`, so a filter like `user_sub` is silently dropped (there's a test that tries exactly this), and
  - when the value isn't `None`, so "no filter" doesn't become "must be empty".

```python
    return [
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_vector,
```

- The first stage, `$vectorSearch`. MongoDB requires it to be the **first** stage of the pipeline.
  - `index`: which vector index to use.
  - `path`: which field holds the embeddings.
  - `queryVector`: the query's embedding (from Voyage), which the stored embeddings are compared against.

```python
                "numCandidates": limit * 20,
                "limit": limit,
```

- The index finds *approximately* the closest matches, which is what makes it fast. `numCandidates` is how many it considers before picking the best `limit`. MongoDB recommends considering at least 20 times as many as you return, for accurate results, so with `limit` 5, it considers 100.

```python
                "filter": {"$and": conditions},
            }
        },
```

- Only answers matching **all** the conditions (`$and`) are considered, including `visibility: "shared"`. Filtering inside `$vectorSearch` like this is called **pre-filtering**: unwanted answers are excluded before ranking, not afterwards.

```python
        {"$set": {"search_score": {"$meta": "vectorSearchScore"}}},
```

- The second stage adds a `search_score` field to each result: how similar it was to the query, from 0 to 1, where higher means more similar. `$meta` reads information that the search produced, rather than a stored field.

```python
        {"$unset": "embedding"},
    ]
```

- The third stage removes the 1024 numbers from each result. Nobody needs them after the search, and leaving them out makes the results much smaller to send around.

### `AnswerSearch`

```python
class AnswerSearch:
    def __init__(self, db: AsyncDatabase, settings: Settings, available: bool):
        self.db = db
        self.settings = settings
        self.available = available
```

- A small class holding what a search needs: the database, the settings, and whether vector search is available. It's created once at startup in `main.py`.
- Wrapping search in a class means tests can replace it with `InMemoryAnswerSearch` (chapter 08), which has the same `search` method but works on any database, including the one GitHub Actions uses.

```python
    async def search(self, query_vector: list[float], filters: dict, limit: int = 5) -> list[dict]:
        pipeline = build_search_pipeline(query_vector, filters, limit, self.settings.vector_index_name)
        cursor = await self.db.answers.aggregate(pipeline)
        return await cursor.to_list()
```

- Builds the pipeline, runs it with `aggregate`, and reads all the results into a list.
- Each result is a whole answer document (minus its embedding), plus `search_score`, most similar first.
