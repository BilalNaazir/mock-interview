"""
worker.py - The background worker. A separate program from the API.

Run with:   python -m app.worker
(Docker Compose runs it for you as the "worker" service.)

It loops forever: wait for a job on the SQS queue, process it, repeat.
You can run several copies to process more answers at once; SQS makes sure
each job goes to only one worker at a time.
"""

import logging
import os
import signal
import sys

from pymongo import MongoClient

from app.config import get_settings
from app.processing import WorkerContext, handle_job
from app.queue import JobQueue
from app.scoring import ClaudeScorer
from app.storage import VideoStorage
from app.transcription import WhisperTranscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mock_interview.worker")


class ShutdownFlag:
    """
    GRACEFUL SHUTDOWN: when Docker (or AWS, in Phase 6) wants to stop the
    worker, it sends a "please stop" signal (SIGTERM). Instead of dying
    mid-job, we note it, finish the current job, and then exit cleanly.
    """

    def __init__(self):
        self.stopping = False
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)  # Ctrl+C

    def request_stop(self, *_args):
        logger.info("Shutdown requested - finishing the current job first")
        self.stopping = True


def main() -> None:
    settings = get_settings()

    queue = JobQueue(settings)
    if not queue.is_configured:
        logger.error("SQS_PROCESSING_QUEUE_URL is not set, so there are no jobs to process. Exiting.")
        sys.exit(1)

    # Check for the key now, at startup. The anthropic library only complains
    # when it's first USED, so without this check you'd only find out when
    # every knowledge answer failed - a confusing way to discover a typo.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY is not set, so answers can't be scored. Exiting.")
        sys.exit(1)
    scorer = ClaudeScorer(settings.scoring_model)

    ctx = WorkerContext(
        db=MongoClient(settings.mongodb_uri)[settings.mongodb_db_name],
        storage=VideoStorage(settings),
        transcriber=WhisperTranscriber(settings.whisper_model, settings.whisper_compute_type),
        scorer=scorer,
        settings=settings,
    )
    shutdown = ShutdownFlag()
    logger.info("Worker started in '%s' environment, waiting for jobs...", settings.environment)

    while not shutdown.stopping:
        for job in queue.receive_jobs():
            if handle_job(job, ctx):
                queue.delete_job(job)

    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
