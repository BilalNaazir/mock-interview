"""
vector_search.py - Finding shared answers by meaning, with MongoDB Vector Search.

How it works:
  1. Every finished answer has an "embedding" field (1024 numbers).
  2. A VECTOR SEARCH INDEX on that field lets MongoDB quickly find the
     embeddings closest to a query's embedding - without comparing against
     every single answer.
  3. A search runs an aggregation pipeline that starts with $vectorSearch.

Vector search needs MongoDB Atlas (in the cloud) or the "Atlas Local" Docker
image (on your laptop). On an ordinary MongoDB, creating the index fails, so
the app carries on with search switched off instead of crashing.
"""

import logging

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.operations import SearchIndexModel

from app.config import Settings

logger = logging.getLogger("mock_interview.vector_search")

# The fields a search can filter on. Atlas only allows filtering on fields
# that are declared in the index as type "filter".
FILTER_FIELDS = ("visibility", "interview_slug", "question_order", "question_type")


def vector_index_definition(settings: Settings) -> dict:
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",                        # the field holding the numbers
                "numDimensions": settings.embedding_dimensions,
                "similarity": "cosine",                     # how "closeness" is measured
            },
            *({"type": "filter", "path": field} for field in FILTER_FIELDS),
        ]
    }


async def ensure_vector_index(db: AsyncDatabase, settings: Settings) -> bool:
    """
    Create the vector index if it doesn't exist yet.
    Returns True if vector search is available, False if it isn't.
    """
    try:
        # The collection must exist before a search index can be put on it.
        try:
            await db.create_collection("answers")
        except CollectionInvalid:
            pass  # it already exists - the usual case

        cursor = await db.answers.list_search_indexes(settings.vector_index_name)
        if not await cursor.to_list():
            await db.answers.create_search_index(
                SearchIndexModel(
                    definition=vector_index_definition(settings),
                    name=settings.vector_index_name,
                    type="vectorSearch",
                )
            )
            # The index builds in the background, usually within seconds.
            logger.info("Created vector search index '%s'", settings.vector_index_name)
        return True
    except OperationFailure as error:
        logger.warning("Vector search is unavailable on this database (%s) - search is switched off", error)
        return False


def build_search_pipeline(query_vector: list[float], filters: dict, limit: int, index_name: str) -> list[dict]:
    """
    The aggregation pipeline for one search. It ALWAYS includes
    visibility = "shared", whatever filters are passed in, so a private answer
    can never be returned - this is enforced here, in code.
    """
    conditions = [{"visibility": "shared"}]
    conditions += [{field: value} for field, value in filters.items() if field in FILTER_FIELDS and value is not None]
    return [
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_vector,
                # Look at 20x more candidates than we return, as MongoDB
                # recommends, so the approximate search finds the best ones.
                "numCandidates": limit * 20,
                "limit": limit,
                "filter": {"$and": conditions},
            }
        },
        # Add how close each answer was (0 to 1, higher = more similar)...
        {"$set": {"search_score": {"$meta": "vectorSearchScore"}}},
        # ...and drop the 1024 numbers, which nobody needs to see.
        {"$unset": "embedding"},
    ]


class AnswerSearch:
    """Runs vector searches over shared answers."""

    def __init__(self, db: AsyncDatabase, settings: Settings, available: bool):
        self.db = db
        self.settings = settings
        self.available = available

    async def search(self, query_vector: list[float], filters: dict, limit: int = 5) -> list[dict]:
        pipeline = build_search_pipeline(query_vector, filters, limit, self.settings.vector_index_name)
        cursor = await self.db.answers.aggregate(pipeline)
        return await cursor.to_list()
