"""
queue.py - The SQS job queue between the API and the worker.

This is the restaurant's order rail from our earlier conversation:
  - The API (the waiter) pins a small job onto the queue: "process the
    recording with this ID". It then replies to the user straight away.
  - The worker (the cook) takes jobs off the queue one at a time and does
    the slow work: transcribing and scoring.

A job message only holds IDs, never the video itself. Queue messages are
meant to be tiny; the video stays in S3 and the details stay in MongoDB.

How SQS keeps jobs safe:
  - When the worker RECEIVES a job, SQS hides it from other workers for a
    while (the "visibility timeout") instead of deleting it.
  - If the worker finishes, it DELETES the job.
  - If the worker crashes, the job reappears after the timeout and is retried.
  - After too many failed tries, SQS moves it to a DEAD-LETTER QUEUE, a
    separate queue where failed jobs wait for a human to look at them.
"""

import json
from dataclasses import dataclass

import boto3
from fastapi import Request

from app.config import Settings


@dataclass
class ReceivedJob:
    body: dict
    receipt_handle: str  # SQS's "ticket" for this delivery, needed to delete it
    receive_count: int   # how many times this job has been handed out (1 = first try)


class JobQueue:
    def __init__(self, settings: Settings):
        self.queue_url = settings.sqs_processing_queue_url
        self.client = boto3.client("sqs", region_name=settings.aws_region)

    @property
    def is_configured(self) -> bool:
        return bool(self.queue_url)

    # --- Used by the API -----------------------------------------------------

    def send_processing_job(self, answer_id: str, recording_id: str) -> None:
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"type": "process_recording", "answer_id": answer_id, "recording_id": recording_id}),
        )

    # --- Used by the worker --------------------------------------------------

    def receive_jobs(self, visibility_timeout: int = 300) -> list[ReceivedJob]:
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            # LONG POLLING: if the queue is empty, wait up to 20 seconds for a
            # job to arrive before replying. Cheaper and faster than asking
            # over and over (the same idea as long polling from our list of
            # ways for programs to talk).
            WaitTimeSeconds=20,
            # Hide the job from other workers for 5 minutes while we work.
            VisibilityTimeout=visibility_timeout,
            # Ask SQS to tell us how many times this job has been delivered.
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        return [
            ReceivedJob(
                body=json.loads(message["Body"]),
                receipt_handle=message["ReceiptHandle"],
                receive_count=int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1")),
            )
            for message in response.get("Messages", [])
        ]

    def delete_job(self, job: ReceivedJob) -> None:
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=job.receipt_handle)


def get_queue(request: Request) -> JobQueue:
    """FastAPI dependency: the JobQueue created at startup (see main.py)."""
    return request.app.state.queue
