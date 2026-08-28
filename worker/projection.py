from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def project_event(
    connection: Connection,
    event: dict[str, Any],
) -> None:

    event_type = event["event_type"]

    if event_type == "agent.start":
        _start_trace(connection, event)

    elif event_type == "agent.end":
        _end_trace(connection, event)

    elif event_type.endswith(".start"):
        _start_span(connection, event)

    elif event_type.endswith(".end"):
        _end_span(connection, event)


def _start_trace(
    connection: Connection,
    event: dict[str, Any],
) -> None:

    query = """
        INSERT INTO traces (
            trace_id,
            name,
            status,
            started_at,
            payload
        )
        VALUES (
            %(trace_id)s,
            %(name)s,
            'running',
            %(timestamp)s,
            %(payload)s
        )
        ON CONFLICT (trace_id) DO NOTHING
    """

    params = {
        "trace_id": event["trace_id"],
        "name": event["name"],
        "timestamp": event["timestamp"],
        "payload": Jsonb(event.get("payload") or {}),
    }

    _execute(connection, query, params)


def _end_trace(
    connection: Connection,
    event: dict[str, Any],
) -> None:

    payload = event.get("payload", {})

    query = """
        UPDATE traces
        SET
            status = %(status)s,
            ended_at = %(timestamp)s,
            duration_ms = %(duration_ms)s,

            error_type = %(error_type)s,
            error_message = %(error_message)s,
            failure_stage = %(failure_stage)s,

            updated_at = NOW()
        WHERE trace_id = %(trace_id)s
    """


    params = {
        "trace_id": event["trace_id"],
        "status": event["status"],
        "timestamp": event["timestamp"],
        "duration_ms": event.get("duration_ms"),

        "error_type": payload.get("error_type"),
        "error_message": payload.get("error_message"),
        "failure_stage": payload.get("failure_stage"),
    }

    _execute(connection, query, params)


def _start_span(
    connection: Connection,
    event: dict[str, Any],
) -> None:

    span_type = event["event_type"].removesuffix(
        ".start"
    )

    query = """
        INSERT INTO spans (
            span_id,
            trace_id,
            parent_span_id,
            span_type,
            name,
            status,
            started_at,
            payload
        )
        VALUES (
            %(span_id)s,
            %(trace_id)s,
            %(parent_span_id)s,
            %(span_type)s,
            %(name)s,
            'running',
            %(timestamp)s,
            %(payload)s
        )
        ON CONFLICT (span_id) DO NOTHING
    """

    params = {
        "span_id": event["span_id"],
        "trace_id": event["trace_id"],
        "parent_span_id": event.get(
            "parent_span_id"
        ),
        "span_type": span_type,
        "name": event["name"],
        "timestamp": event["timestamp"],
        "payload": Jsonb(event.get("payload") or {}),
    }

    _execute(connection, query, params)


def _end_span(
    connection: Connection,
    event: dict[str, Any],
) -> None:

    # Merge, not overwrite: `payload || jsonb` keeps keys that were
    # set on the .start event (e.g. tool arguments) while letting the
    # .end event add or override keys (e.g. return value, llm usage).
    # Previously the end payload replaced the start payload outright,
    # silently erasing start-side fields once they diverged.
    query = """
        UPDATE spans
        SET
            status = %(status)s,
            ended_at = %(timestamp)s,
            duration_ms = %(duration_ms)s,
            payload = COALESCE(payload, '{}'::jsonb) || %(payload)s,
            updated_at = NOW()
        WHERE span_id = %(span_id)s
    """

    params = {
        "span_id": event["span_id"],
        "status": event["status"],
        "timestamp": event["timestamp"],
        "duration_ms": event.get("duration_ms"),
        "payload": Jsonb(event.get("payload") or {}),
    }

    _execute(connection, query, params)


def _execute(
    connection: Connection,
    query: str,
    params: dict[str, Any],
) -> None:

    with connection.cursor() as cursor:
        cursor.execute(query, params)