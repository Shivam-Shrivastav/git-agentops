from __future__ import annotations

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from app.database import get_connection


router = APIRouter(
    prefix="/traces",
    tags=["traces"],
)


@router.get("")
def list_traces(limit: int = 50):
    """
    Return recent AgentOps traces.

    Newest traces are returned first.
    """

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 100",
        )

    query = """
        SELECT
            trace_id,
            name,
            status,
            started_at,
            ended_at,
            duration_ms
        FROM traces
        ORDER BY started_at DESC
        LIMIT %s
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (limit,))
            traces = cursor.fetchall()

    return traces


@router.get("/{trace_id}")
def get_trace(trace_id: str):
    """
    Return metadata for one AgentOps trace.
    """

    query = """
        SELECT
            trace_id,
            name,
            status,
            started_at,
            ended_at,
            duration_ms,
            COALESCE(payload->>'user_query', payload->>'task') AS user_query
        FROM traces
        WHERE trace_id = %s
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (trace_id,))
            trace = cursor.fetchone()

    if trace is None:
        raise HTTPException(
            status_code=404,
            detail="Trace not found",
        )

    return trace




@router.get("/{trace_id}/spans")
def get_trace_spans(trace_id: str):
    """
    Return all spans belonging to a trace.

    Spans are ordered by start time so the caller can
    reconstruct the execution sequence/tree using
    span_id + parent_span_id.
    """

    trace_query = """
        SELECT trace_id
        FROM traces
        WHERE trace_id = %s
    """

    spans_query = """
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
        WHERE trace_id = %s
        ORDER BY started_at ASC
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:

            # Distinguish "trace exists with zero spans"
            # from "trace does not exist".
            cursor.execute(trace_query, (trace_id,))
            trace = cursor.fetchone()

            if trace is None:
                raise HTTPException(
                    status_code=404,
                    detail="Trace not found",
                )

            cursor.execute(spans_query, (trace_id,))
            spans = cursor.fetchall()

    return spans


@router.get("/{trace_id}/tree")
def get_trace_tree(trace_id: str):
    """ 
    Return a trace and its spans as a hierarchical execution tree.
    """

    trace_query = """
        SELECT
            trace_id,
            name,
            status,
            started_at,
            ended_at,
            duration_ms,
            COALESCE(payload->>'user_query', payload->>'task') AS user_query
        FROM traces
        WHERE trace_id = %s
    """

    spans_query = """
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
        WHERE trace_id = %s
        ORDER BY started_at ASC
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:

            cursor.execute(trace_query, (trace_id,))
            trace = cursor.fetchone()

            if trace is None:
                raise HTTPException(
                    status_code=404,
                    detail="Trace not found",
                )

            cursor.execute(spans_query, (trace_id,))
            spans = cursor.fetchall()

    # Create one tree node for every span.
    nodes = {}

    for span in spans:
        span_dict = dict(span)

        node = {
            **span_dict,
            "children": [],
        }

        nodes[span["span_id"]] = node

    root_children = []

    # Connect each node to its parent.
    for span in spans:
        span_id = span["span_id"]
        parent_span_id = span["parent_span_id"]

        node = nodes[span_id]

        if parent_span_id in nodes:
            nodes[parent_span_id]["children"].append(node)
        else:
            # Parent may be the agent/root span, which is represented
            # by the trace rather than by a row in the spans table.
            root_children.append(node)

    return {
        "trace": dict(trace),
        "children": root_children,
    }


@router.get("/{trace_id}/usage")
def get_trace_usage(trace_id: str):
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:

            # Make sure the trace actually exists.
            cursor.execute(
                """
                SELECT 1
                FROM traces
                WHERE trace_id = %s
                """,
                (trace_id,),
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Trace not found",
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS llm_calls,

                    COALESCE(
                        SUM((payload->>'input_tokens')::BIGINT),
                        0
                    ) AS input_tokens,

                    COALESCE(
                        SUM((payload->>'output_tokens')::BIGINT),
                        0
                    ) AS output_tokens,

                    COALESCE(
                        SUM((payload->>'total_tokens')::BIGINT),
                        0
                    ) AS total_tokens,

                    COALESCE(
                        SUM((payload->>'cost_usd')::NUMERIC),
                        0
                    ) AS cost_usd,

                    COALESCE(
                        SUM(duration_ms),
                        0
                    ) AS llm_duration_ms

                FROM spans
                WHERE trace_id = %s
                  AND span_type = 'llm'
                """,
                (trace_id,),
            )

            row = cursor.fetchone()

    return {
        "trace_id": str(trace_id),
        "llm_calls": row["llm_calls"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "cost_usd": float(row["cost_usd"]),
        "llm_duration_ms": float(row["llm_duration_ms"]),
    }


@router.get("/{trace_id}/decisions")
def get_trace_decisions(trace_id: str):
    """
    Return the planner decisions for one trace, in execution order.

    Each row is one planner step with the decision fields lifted out
    of the JSONB payload into structured columns so the UI can render
    the "why did the agent decide this" timeline without parsing
    raw payloads. This is the per-trace reasoning view.
    """

    trace_check = """
        SELECT 1 FROM traces WHERE trace_id = %s
    """

    decisions_query = """
        SELECT
            span_id,
            status,
            started_at,
            ended_at,
            duration_ms,
            (payload->>'iteration')::int AS iteration,
            payload->>'thought' AS thought,
            payload->>'chosen_action' AS chosen_action,
            payload->'candidates' AS candidates,
            payload->'rejected_actions' AS rejected_actions,
            (payload->>'confidence')::float AS confidence,
            payload->>'model' AS model,
            payload->>'error' AS error,
            (payload->>'budget_exceeded')::boolean AS budget_exceeded,
            payload->>'final_response' AS final_response,
            payload->'token_usage' AS token_usage
        FROM spans
        WHERE trace_id = %s
          AND span_type = 'planner'
        ORDER BY started_at ASC
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(trace_check, (trace_id,))
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Trace not found",
                )

            cursor.execute(decisions_query, (trace_id,))
            decisions = cursor.fetchall()

    return decisions


@router.get("/{trace_id}/decision-quality")
def get_trace_decision_quality(trace_id: str) -> dict:
    """
    Return the LLM-judge decision-quality evaluation for a trace, if
    one was recorded.

    The agent records the judge's score/critique as a
    ``decision-quality-judge`` LLM span (a child of the trace); this
    endpoint lifts those fields out of the span payload into a
    structured response for the dashboard's Decision Quality panel.
    """

    query = """
        SELECT
            span_id,
            status,
            started_at,
            duration_ms,
            payload
        FROM spans
        WHERE trace_id = %s
          AND span_type = 'llm'
          AND name = 'decision-quality-judge'
        ORDER BY started_at DESC
        LIMIT 1
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (trace_id,))
            row = cursor.fetchone()

    # A judge span only counts as an evaluation when it completed
    # successfully. The free model sometimes errors mid-judge; reporting
    # those as "evaluated" with no score is misleading, so treat an
    # errored judge span as not-evaluated (the panel stays hidden).
    if row is None or row["status"] != "success":
        return {"evaluated": False}

    payload = row["payload"] or {}

    return {
        "evaluated": True,
        "span_id": row["span_id"],
        "status": row["status"],
        "duration_ms": row["duration_ms"],
        "score": payload.get("eval_score"),
        "summary": payload.get("eval_summary"),
        "strengths": payload.get("eval_strengths"),
        "weaknesses": payload.get("eval_weaknesses"),
        "model": payload.get("model"),
        "input_tokens": payload.get("input_tokens"),
        "output_tokens": payload.get("output_tokens"),
        "completion": payload.get("completion"),
    }


def get_trace_error(
    trace_id: str,
) -> dict | None:

    query = """
        SELECT
            trace_id,
            status,
            failure_stage,
            error_type,
            error_message
        FROM traces
        WHERE trace_id = %s
    """

    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row
        ) as cursor:

            cursor.execute(
                query,
                (trace_id,),
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return row

@router.get(
    "/{trace_id}/error"
)
def trace_error(
    trace_id: str,
):

    result = get_trace_error(trace_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Trace not found",
        )

    return result


