"""
seed.py - The five interviews, loaded into MongoDB when the app starts.

"Seeding" means filling the database with starting data. Each interview has
3 knowledge questions followed by 2 situational questions.

Knowledge questions carry a list of key_points: the ideas a strong answer
should cover. The AI evaluator will use these as a marking rubric in a later
phase. They're stored in the database but deliberately NOT included in the
API response models (see models.py), so candidates can't read the rubric.

Situational questions have no key_points, because they're judged against the
STAR method (Situation, Task, Action, Result) instead.

Seeding is IDEMPOTENT: running it many times gives the same result as running
it once (we "upsert" by slug). So restarting the app never creates duplicates,
and editing a question here updates it on the next start.
"""

from pymongo.asynchronous.database import AsyncDatabase

INTERVIEWS = [
    {
        "slug": "backend-python",
        "title": "Backend (Python)",
        "description": "APIs, async programming and data handling with Python.",
        "questions": [
            {
                "order": 1,
                "type": "knowledge",
                "text": "What is the difference between async and sync endpoints in FastAPI, and when would you use each?",
                "key_points": [
                    "async endpoints run on the event loop and should only await non-blocking work",
                    "blocking calls inside async endpoints freeze the whole server",
                    "sync endpoints run in a thread pool",
                    "choose based on whether the libraries you call are async",
                ],
            },
            {
                "order": 2,
                "type": "knowledge",
                "text": "How would you design a REST API for a resource like 'orders'? Talk about endpoints, status codes and validation.",
                "key_points": [
                    "resource-based URLs with HTTP methods (GET, POST, PUT/PATCH, DELETE)",
                    "correct status codes such as 200, 201, 400, 404, 422",
                    "input validation, for example with Pydantic",
                    "pagination and filtering for lists",
                ],
            },
            {
                "order": 3,
                "type": "knowledge",
                "text": "Explain what a database index is, and the trade-offs of adding one.",
                "key_points": [
                    "speeds up reads by avoiding full scans",
                    "slows down writes and uses extra storage",
                    "unique indexes enforce data rules",
                    "index the fields you filter and sort by",
                ],
            },
            {
                "order": 4,
                "type": "situational",
                "text": "Tell me about a time a production API you worked on became slow or unreliable. How did you handle it?",
            },
            {
                "order": 5,
                "type": "situational",
                "text": "Describe a time you had to change an API that other teams or clients depended on.",
            },
        ],
    },
    {
        "slug": "backend-node",
        "title": "Backend (Node.js)",
        "description": "The event loop, APIs and error handling in Node.js.",
        "questions": [
            {
                "order": 1,
                "type": "knowledge",
                "text": "Explain the Node.js event loop and why CPU-heavy work can be a problem.",
                "key_points": [
                    "single-threaded JavaScript execution with non-blocking I/O",
                    "callbacks and promises are queued and run when the stack is empty",
                    "CPU-heavy work blocks every other request",
                    "worker threads or separate services for heavy computation",
                ],
            },
            {
                "order": 2,
                "type": "knowledge",
                "text": "How do you handle errors in an Express or Fastify API so they don't crash the server?",
                "key_points": [
                    "centralised error-handling middleware",
                    "catching rejected promises in async handlers",
                    "consistent error response format and status codes",
                    "logging errors without leaking internal details to users",
                ],
            },
            {
                "order": 3,
                "type": "knowledge",
                "text": "What is the difference between authentication and authorization, and how would you implement both in a Node API?",
                "key_points": [
                    "authentication verifies identity, authorization checks permissions",
                    "verifying tokens such as JWTs in middleware",
                    "role or ownership checks per route",
                    "never trusting the client to enforce permissions",
                ],
            },
            {
                "order": 4,
                "type": "situational",
                "text": "Tell me about a time you tracked down a difficult bug in a backend service.",
            },
            {
                "order": 5,
                "type": "situational",
                "text": "Describe a situation where you had to balance shipping quickly against code quality.",
            },
        ],
    },
    {
        "slug": "frontend-react",
        "title": "Frontend (React)",
        "description": "Components, state management and performance in React.",
        "questions": [
            {
                "order": 1,
                "type": "knowledge",
                "text": "What is the difference between state and props in React?",
                "key_points": [
                    "props are passed in from the parent and are read-only",
                    "state is owned by the component and changes over time",
                    "changing state triggers a re-render",
                    "lifting state up to share it between components",
                ],
            },
            {
                "order": 2,
                "type": "knowledge",
                "text": "When does a React component re-render, and how can you avoid unnecessary re-renders?",
                "key_points": [
                    "re-renders on state change, parent re-render, or context change",
                    "memo, useMemo and useCallback to skip unnecessary work",
                    "keeping state as local as possible",
                    "measuring with the React DevTools profiler before optimising",
                ],
            },
            {
                "order": 3,
                "type": "knowledge",
                "text": "How do you fetch data from an API in React, and how do you handle loading and error states?",
                "key_points": [
                    "fetching in an effect or with a library such as TanStack Query",
                    "separate loading, error and success states in the UI",
                    "avoiding race conditions and updates after unmount",
                    "caching and refetching strategies",
                ],
            },
            {
                "order": 4,
                "type": "situational",
                "text": "Tell me about a time you improved the performance or user experience of a frontend app.",
            },
            {
                "order": 5,
                "type": "situational",
                "text": "Describe a time you disagreed with a designer or product manager about how a feature should work.",
            },
        ],
    },
    {
        "slug": "agentic-ai",
        "title": "Agentic AI",
        "description": "Agents, tools, retrieval and evaluation of LLM systems.",
        "questions": [
            {
                "order": 1,
                "type": "knowledge",
                "text": "What is the difference between a fixed LLM workflow and an agent, and when would you choose each?",
                "key_points": [
                    "workflows follow predefined steps, agents choose their own steps",
                    "workflows are more predictable, cheaper and easier to test",
                    "agents suit open-ended tasks where the path is unknown",
                    "start with a workflow and move to an agent only when needed",
                ],
            },
            {
                "order": 2,
                "type": "knowledge",
                "text": "How does tool use (function calling) work with an LLM?",
                "key_points": [
                    "tools are described to the model with a name, description and input schema",
                    "the model requests a tool call; the application executes it",
                    "the result is sent back to the model to continue",
                    "clear tool descriptions strongly affect behaviour",
                ],
            },
            {
                "order": 3,
                "type": "knowledge",
                "text": "Explain retrieval-augmented generation (RAG) and how you would evaluate whether a RAG pipeline is working well.",
                "key_points": [
                    "retrieve relevant documents, then give them to the model as context",
                    "embeddings and vector search for semantic retrieval",
                    "evaluate retrieval quality and answer quality separately",
                    "tracing and observability tools to inspect each step",
                ],
            },
            {
                "order": 4,
                "type": "situational",
                "text": "Tell me about a time an AI or LLM feature you built behaved unexpectedly. What did you do?",
            },
            {
                "order": 5,
                "type": "situational",
                "text": "Describe a time you had to reduce the cost or latency of an AI system.",
            },
        ],
    },
    {
        "slug": "devops-docker",
        "title": "DevOps (Docker)",
        "description": "Containers, CI/CD pipelines and running services in production.",
        "questions": [
            {
                "order": 1,
                "type": "knowledge",
                "text": "What is the difference between a Docker image and a container?",
                "key_points": [
                    "an image is a read-only blueprint built from a Dockerfile",
                    "a container is a running instance of an image",
                    "many containers can run from one image",
                    "images are stored and shared through registries",
                ],
            },
            {
                "order": 2,
                "type": "knowledge",
                "text": "How would you make a Dockerfile for a Python web app smaller, faster to build and more secure?",
                "key_points": [
                    "slim or minimal base images",
                    "ordering layers so dependencies are cached before code changes",
                    "running as a non-root user",
                    "a .dockerignore file and no secrets baked into the image",
                ],
            },
            {
                "order": 3,
                "type": "knowledge",
                "text": "Describe a CI/CD pipeline that takes code from a pull request to production safely.",
                "key_points": [
                    "automated tests and linting on every pull request",
                    "building an image once and promoting the same image through environments",
                    "deploying to staging before production",
                    "approval gates, rollbacks and monitoring after release",
                ],
            },
            {
                "order": 4,
                "type": "situational",
                "text": "Tell me about a time a deployment went wrong. How did you respond?",
            },
            {
                "order": 5,
                "type": "situational",
                "text": "Describe a time you automated a manual process for your team.",
            },
        ],
    },
]


async def seed_interviews(db: AsyncDatabase) -> None:
    """Insert or update every interview, matched by its slug."""
    for interview in INTERVIEWS:
        await db.interviews.update_one(
            {"slug": interview["slug"]},
            {"$set": interview},
            upsert=True,
        )
