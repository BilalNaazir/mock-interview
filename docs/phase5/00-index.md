# Phase 5 code walkthrough

This folder explains **every piece of code written in Phase 5**, line by line: what each line does, what each function is for, and **where and when** it's used.

Read the chapters in order. They follow the journey of an answer: it gets **shared**, the worker turns it into an **embedding**, it's found by **vector search**, the **search agent** decides what matches, the **API** returns it, and the **React pages** show it. The last chapter explains the **tests**.

| Chapter | What it covers | Files |
|---|---|---|
| [01 Settings and startup](01-settings-and-startup.md) | New settings, Docker, database indexes, switching search on at startup | `config.py`, `requirements*.txt`, `.env.example`, `docker-compose.yml`, `db.py`, `main.py` |
| [02 Sharing](02-sharing.md) | Choosing which answers others can see | `models.py`, `routers/attempts.py`, `api.ts`, `types.ts`, `ShareToggle.tsx`, `AttemptReviewPage.tsx` |
| [03 Embeddings](03-embeddings.md) | Turning answers into lists of numbers | `embeddings.py`, `processing.py`, `worker.py`, `backfill_embeddings.py` |
| [04 Vector search](04-vector-search.md) | Finding answers by meaning in MongoDB | `vector_search.py` |
| [05 The search agent](05-search-agent.md) | Claude deciding how to search, with guardrails | `search_agent.py` |
| [06 The Community API](06-community-api.md) | The endpoints the pages call | `routers/community.py`, `models.py` |
| [07 The Community pages](07-community-pages.md) | What the user sees | `AnswerCard.tsx`, `CommunityPage.tsx`, `SharedAnswerPage.tsx`, `App.tsx`, `Header.tsx`, `index.css` |
| [08 The tests](08-tests.md) | How each rule is proven | `tests/helpers.py`, `conftest.py`, `test_sharing.py`, `test_community.py`, `test_search_agent.py`, `test_embeddings.py` |

## The whole journey in one picture

```
 Owner ticks "Share"          Worker finishes an answer           Someone asks a question
        │                              │                                   │
        ▼                              ▼                                   ▼
 PUT .../visibility           embed_answer()                      POST /community/search
 visibility = "shared"        Voyage: text ──> 1024 numbers       SearchAgent.run()
        │                     saved as answer.embedding              │  list_interviews
        │                              │                             │  search_answers ──> Voyage (query)
        └──────────────┬───────────────┘                             │        └──> $vectorSearch
                       ▼                                             │             (shared only)
               MongoDB "answers"  <──────────────────────────────────┘  submit_answer
                       │                                                     │
                       ▼                                                     ▼
        GET /community/answers                                code keeps only real IDs
        (browse, no AI)                                       ──> reply + answer cards
```

## A few words used throughout

- **Embedding:** a list of numbers (1024 here) representing what a piece of text *means*. Similar meanings give similar numbers.
- **Vector:** another name for that list of numbers.
- **Vector search:** finding the stored vectors closest to a query's vector, which means finding text with the closest meaning.
- **Index:** a structure that makes lookups fast, like the index at the back of a book. A **vector index** does this for embeddings.
- **Dependency injection:** handing a function the things it needs from outside, instead of it creating them itself. It's how tests swap in fakes, and it appears in almost every file.
