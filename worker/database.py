from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://agentops:agentops@localhost:5432/agentops",
)


# --- connection pooling -------------------------------------------------
#
# A module-level psycopg_pool.ConnectionPool reuses connections across
# events instead of opening a fresh one per call. If psycopg_pool is not
# installed we fall back to a plain connect()/close() so the worker still
# runs in a minimal dev environment.
_pool: Any = None


def _get_pool() -> Any:
    global _pool

    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=10,
                open=True,
            )
        except Exception:
            # psycopg_pool missing OR database not reachable yet.
            # Fall back to one-shot connections.
            _pool = False

    return _pool


@contextmanager
def get_connection() -> Iterator[Connection]:
    """
    Yield a database connection.

    Used as `with get_connection() as connection:`. With a pool the
    connection is checked back in on exit (commit on success, rollback
    on exception). Without a pool a fresh connection is opened and
    closed each call, preserving the original MVP behaviour.
    """

    pool = _get_pool()

    if pool:
        with pool.connection() as connection:
            yield connection
        return

    connection = psycopg.connect(DATABASE_URL)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# --- event persistence --------------------------------------------------


def save_event(
    connection: Connection,
    event: dict[str, Any],
) -> bool:
    """
    Persist one raw AgentOps event.

    Returns:
        True  -> event was inserted
        False -> event already existed

    The caller owns the transaction.
    """

    query = """
        INSERT INTO events (
            event_id,
            trace_id,
            span_id,
            parent_span_id,
            timestamp,
            event_type,
            name,
            status,
            duration_ms,
            payload
        )
        VALUES (
            %(event_id)s,
            %(trace_id)s,
            %(span_id)s,
            %(parent_span_id)s,
            %(timestamp)s,
            %(event_type)s,
            %(name)s,
            %(status)s,
            %(duration_ms)s,
            %(payload)s
        )
        ON CONFLICT (event_id) DO NOTHING
        RETURNING event_id
    """

    params = {
        "event_id": event["event_id"],
        "trace_id": event["trace_id"],
        "span_id": event["span_id"],
        "parent_span_id": event.get("parent_span_id"),
        "timestamp": event["timestamp"],
        "event_type": event["event_type"],
        "name": event["name"],
        "status": event["status"],
        "duration_ms": event.get("duration_ms"),
        "payload": Jsonb(event.get("payload") or {}),
    }

    with connection.cursor() as cursor:
        cursor.execute(query, params)

        inserted = cursor.fetchone()

    return inserted is not None