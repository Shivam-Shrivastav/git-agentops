from __future__ import annotations

import json
import os
import time
from typing import Any

from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from database import get_connection, save_event
from projection import project_event


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

QUEUE_NAME = "agentops:events"
PROCESSING_QUEUE_NAME = "agentops:events:processing"


redis_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=10,
    health_check_interval=30,
)


def process_event(event: dict[str, Any]) -> bool:
    """
    Persist the raw event and update its projection
    atomically.

    Returns:
        True  -> new event processed
        False -> event already processed
    """

    with get_connection() as connection:

        inserted = save_event(
            connection,
            event,
        )

        if not inserted:
            return False

        project_event(
            connection,
            event,
        )

    return True


def reserve_event() -> str | None:
    """
    Atomically move one event from the main queue into
    the processing queue.
    """

    return redis_client.blmove(
        QUEUE_NAME,
        PROCESSING_QUEUE_NAME,
        timeout=5,
        src="LEFT",
        dest="RIGHT",
    )


def acknowledge_event(raw_event: str) -> None:
    """
    Remove an event from the processing queue after
    successful/idempotent processing.
    """

    removed = redis_client.lrem(
        PROCESSING_QUEUE_NAME,
        1,
        raw_event,
    )

    if removed == 0:
        print(
            "[AgentOps Worker] Warning: "
            "event not found during ACK"
        )


def recover_abandoned_events() -> int:
    """
    Requeue anything left in the processing queue.

    Safe for the current single-worker prototype.
    """

    recovered = 0

    while True:

        raw_event = redis_client.lmove(
            PROCESSING_QUEUE_NAME,
            QUEUE_NAME,
            src="LEFT",
            dest="RIGHT",
        )

        if raw_event is None:
            break

        recovered += 1

    return recovered


def run() -> None:
    print("AgentOps worker started")
    print(f"Queue: {QUEUE_NAME}")
    print(f"Processing queue: {PROCESSING_QUEUE_NAME}")

    try:
        recovered = recover_abandoned_events()

        if recovered:
            print(
                f"[recovery] Requeued "
                f"{recovered} abandoned event(s)"
            )

    except (ConnectionError, TimeoutError) as exc:
        print(
            "[AgentOps Worker] "
            f"Startup recovery failed: {exc}"
        )

        return

    while True:

        try:
            raw_event = reserve_event()

            if raw_event is None:
                continue

            try:
                event = json.loads(raw_event)

            except json.JSONDecodeError as exc:
                print(
                    "[AgentOps Worker] "
                    f"Invalid JSON: {exc}"
                )

                # Malformed telemetry cannot become valid
                # through retrying.
                acknowledge_event(raw_event)

                continue

            try:
                # print(
                #     f"[reserved] event={event['event_id'][:8]}"
                # )

                # time.sleep(10)
                inserted = process_event(event)

            except Exception as exc:
                print(
                    "[AgentOps Worker] "
                    f"Event processing failed: {exc}"
                )

                # Do not ACK.
                # Event remains in processing queue.
                continue

            acknowledge_event(raw_event)

            if inserted:

                print(
                    f"[stored] "
                    f"{event['event_type']:<18} "
                    f"{event['name']:<20} "
                    f"event={event['event_id'][:8]} "
                    f"trace={event['trace_id'][:8]}"
                )

            else:

                print(
                    f"[duplicate] "
                    f"{event['event_type']:<18} "
                    f"{event['name']:<20} "
                    f"event={event['event_id'][:8]}"
                )

        except (ConnectionError, TimeoutError) as exc:

            print(
                "[AgentOps Worker] "
                f"Redis connection error: {exc}"
            )

            time.sleep(2)

        except KeyboardInterrupt:

            print("\nAgentOps worker stopped.")

            break


if __name__ == "__main__":
    run()