"""
backfill_embeddings.py - Make older answers searchable.

Answers finished before Phase 5 (or while embedding failed) have no
embedding, so search can't find them. This one-off script embeds them.

Run with:   docker compose exec worker python -m app.backfill_embeddings

"Backfill" means filling in data that was missing from the past. Running it
twice is safe: the second time, nothing is missing, so nothing happens.
"""

import logging

from pymongo import MongoClient

from app.config import get_settings
from app.embeddings import VoyageEmbedder
from app.processing import embed_answer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock_interview.backfill")


def backfill(db, embedder, settings) -> int:
    """Embed every finished answer that has no embedding. Returns how many were embedded."""
    # {"$exists": False} matches documents that don't have the field at all.
    missing = db.answers.find({"status": "answered", "embedding": {"$exists": False}}, {"_id": 1}).to_list()
    embedded = sum(embed_answer(db, embedder, settings, answer["_id"]) for answer in missing)
    logger.info("Embedded %s of %s answers that were missing embeddings", embedded, len(missing))
    return embedded


def main() -> None:
    settings = get_settings()
    if not settings.voyage_api_key.get_secret_value():
        raise SystemExit("VOYAGE_API_KEY is not set")
    db = MongoClient(settings.mongodb_uri)[settings.mongodb_db_name]
    backfill(db, VoyageEmbedder(settings), settings)


if __name__ == "__main__":
    main()
