"""
main.py - Where the backend starts.

Run locally with:   uvicorn app.main:app --reload
(Docker Compose does this for you - see docker-compose.yml.)

Then visit http://localhost:8000/docs for interactive API documentation,
generated automatically by FastAPI from the code.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import connect_to_mongo, create_indexes
from app.embeddings import VoyageEmbedder
from app.queue import JobQueue
from app.routers import attempts, community, health, interviews, live, users
from app.search_agent import SearchAgent
from app.seed import seed_interviews
from app.storage import VideoStorage
from app.vector_search import AnswerSearch, ensure_vector_index

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_interview")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code before `yield` runs once when the app STARTS; code after it runs
    once when the app STOPS. This is the place for setup work, like opening
    the database connection, rather than doing it on every request.
    """
    settings = get_settings()
    client, db = await connect_to_mongo(settings)
    await create_indexes(db)
    await seed_interviews(db)

    # Store shared objects on app.state so endpoints can reach them
    # (see get_db and get_storage).
    app.state.db = db
    app.state.storage = VideoStorage(settings)
    if not app.state.storage.is_configured:
        logger.warning("S3_VIDEOS_BUCKET is not set - recording uploads will be unavailable")
    app.state.queue = JobQueue(settings)
    if not app.state.queue.is_configured:
        logger.warning("SQS_PROCESSING_QUEUE_URL is not set - answers will be stored but not processed")
    await set_up_search(app, db, settings)
    logger.info("Started in '%s' environment, database '%s'", settings.environment, settings.mongodb_db_name)

    yield  # <- the app runs and serves requests here

    await client.close()


async def set_up_search(app: FastAPI, db, settings: Settings) -> None:
    """
    Search needs three things: vector search in the database, a Voyage key
    (to embed queries) and an Anthropic key (for the agent). If any is
    missing, search is switched off - the rest of the app works as normal.
    """
    available = await ensure_vector_index(db, settings) if settings.create_vector_index else False
    app.state.answer_search = AnswerSearch(db, settings, available)
    app.state.search_agent = None

    missing = []
    if not available:
        missing.append("vector search")
    if not settings.voyage_api_key.get_secret_value():
        missing.append("VOYAGE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        logger.warning("Search is switched off - missing: %s", ", ".join(missing))
        return

    app.state.search_agent = SearchAgent(db, app.state.answer_search, VoyageEmbedder(settings), settings)

    logger.info("Search is switched on (vector index '%s')", settings.vector_index_name)


def create_app() -> FastAPI:
    """
    Building the app inside a function (an "app factory") lets the tests
    create a fresh app with their own settings.
    """
    settings = get_settings()
    app = FastAPI(title="Mock Interview API", lifespan=lifespan)

    # CORS: browsers block a website from calling an API on a different
    # address unless the API explicitly allows it. The React dev server runs
    # on localhost:5173 and the API on localhost:8000 - different addresses -
    # so we must list the frontend here. In prod this becomes your real domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(interviews.router)
    app.include_router(attempts.router)
    app.include_router(live.router)
    app.include_router(community.router)
    return app


app = create_app()
