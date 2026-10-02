"""
main.py - Where the backend starts.

Run locally with:   uvicorn app.main:app --reload
(Docker Compose does this for you - see docker-compose.yml.)

Then visit http://localhost:8000/docs for interactive API documentation,
generated automatically by FastAPI from the code.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import connect_to_mongo, create_indexes
from app.routers import health, interviews, users
from app.seed import seed_interviews

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

    # Store the database on app.state so endpoints can reach it (see get_db).
    app.state.db = db
    logger.info("Started in '%s' environment, database '%s'", settings.environment, settings.mongodb_db_name)

    yield  # <- the app runs and serves requests here

    await client.close()


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
    return app


app = create_app()
