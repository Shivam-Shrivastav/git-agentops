from __future__ import annotations

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from app.database import get_connection


router = APIRouter(
    prefix="/spans",
    tags=["spans"],
)


@router.get("")
def list_spans(
    span_type: str | None = None,
    status: str | None = None,
    name: str | None = None,
    chosen_action: str | None = None,
    trace_id: str | None = None,
    limit: int = 50,
):
    """
    Queryable span listing.

    This is the reasoning-queryability surface: callers can filter
    spans on the structured payload (not just on columns). The
    ``chosen_action`` filter in particular lets the UI ask
    "show me every planner step that chose X" or
    "show me every planner step that ended in FINAL/error".

    Filters are AND-combined and all optional. Results are newest
    first.
    """

    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 500",
        )

    # Build the WHERE clause dynamically. We only ever append
    # %-placeholders, so there is no SQL-injection surface here.
    conditions: list[str] = []
    params: list[object] = []

    if span_type is not None:
        conditions.append("span_type = %s")
        params.append(span_type)

    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    if name is not None:
        conditions.append("name = %s")
        params.append(name)

    if trace_id is not None:
        conditions.append("trace_id = %s")
        params.append(trace_id)

    if chosen_action is not None:
        # payload->>'chosen_action' is the planner's chosen action.
        conditions.append("payload->>'chosen_action' = %s")
        params.append(chosen_action)

    where = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    query = f"""
        SELECT
            span_id,
            trace_id,
            parent_span_id,
            span_type,
            name,
            status,
            started_at,
            ended_at,
            duration_ms,
            payload
        FROM spans
        {where}
        ORDER BY started_at DESC
        LIMIT %s
    """
    params.append(limit)

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, tuple(params))
            spans = cursor.fetchall()

    return spans