"""
db.py - Connecting to MongoDB.

We use PyMongo's async client (AsyncMongoClient). "Async" means that while
the backend waits for the database to reply, it can serve other requests
instead of sitting idle - important for a web server handling many users.

MongoDB basics, if you're new to it:
  - A DATABASE holds COLLECTIONS (similar to tables in SQL databases).
  - A collection holds DOCUMENTS, which are JSON-like objects, e.g.
        {"name": "Priya", "email": "priya@example.com"}
  - Documents in one collection don't all need exactly the same fields,
    which suits things like an answer that may or may not have follow-ups.
  - Every document gets a unique "_id" automatically.
"""

from fastapi import Request
from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings


async def connect_to_mongo(settings: Settings) -> tuple[AsyncMongoClient, AsyncDatabase]:
    """Open the connection and make sure the database is reachable."""
    client = AsyncMongoClient(settings.mongodb_uri)
    db = client[settings.mongodb_db_name]

    # "ping" is a tiny command that fails fast if MongoDB isn't reachable,
    # so a wrong address causes a clear error at startup, not on a random
    # request later.
    await client.admin.command("ping")
    return client, db


async def create_indexes(db: AsyncDatabase) -> None:
    """
    Indexes make lookups fast (like the index at the back of a book) and
    can enforce rules. unique=True means MongoDB itself refuses duplicates,
    so even if our code had a bug, we could never end up with two user
    records for the same Cognito account, or two interviews with one slug.

    Creating an index that already exists does nothing, so this is safe
    to run every time the app starts.
    """
    await db.users.create_index([("cognito_sub", ASCENDING)], unique=True)
    await db.interviews.create_index([("slug", ASCENDING)], unique=True)


def get_db(request: Request) -> AsyncDatabase:
    """
    A FastAPI "dependency": any endpoint that needs the database adds
        db: AsyncDatabase = Depends(get_db)
    to its parameters, and FastAPI hands it the database automatically.
    The database object is stored on app.state when the app starts (see main.py).
    """
    return request.app.state.db
