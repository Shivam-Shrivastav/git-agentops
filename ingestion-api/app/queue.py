import json
import os

from redis import Redis


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

QUEUE_NAME = "agentops:events"

redis_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


def enqueue_event(event: dict) -> None:
    redis_client.rpush(
        QUEUE_NAME,
        json.dumps(event),
    )


def enqueue_events(events: list[dict]) -> int:
    """
    Push a batch of events onto the queue in a single Redis pipeline.

    Returns the number of events enqueued.
    """
    if not events:
        return 0

    pipe = redis_client.pipeline()
    for event in events:
        pipe.rpush(QUEUE_NAME, json.dumps(event))
    pipe.execute()

    return len(events)