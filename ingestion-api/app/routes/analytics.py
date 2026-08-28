from __future__ import annotations

from fastapi import APIRouter
from psycopg.rows import dict_row

from app.database import get_connection


router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
)


@router.get("/overview")
def get_overview() -> dict:
    trace_query = """
        SELECT
            COUNT(*) AS total_runs,

            COUNT(*) FILTER (
                WHERE status = 'success'
            ) AS successful_runs,

            COUNT(*) FILTER (
                WHERE status = 'error'
            ) AS failed_runs,

            COALESCE(
                AVG(duration_ms) FILTER (
                    WHERE duration_ms IS NOT NULL
                ),
                0
            ) AS avg_duration_ms

        FROM traces
    """

    llm_query = """
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
        WHERE span_type = 'llm'
    """

    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute(trace_query)
            trace_stats = cursor.fetchone()

            cursor.execute(llm_query)
            llm_stats = cursor.fetchone()

    total_runs = trace_stats["total_runs"]
    successful_runs = trace_stats["successful_runs"]

    success_rate = (
        successful_runs / total_runs * 100
        if total_runs > 0
        else 0
    )

    return {
        **trace_stats,
        "success_rate": round(success_rate, 2),

        "llm_calls": llm_stats["llm_calls"],
        "input_tokens": llm_stats["input_tokens"],
        "output_tokens": llm_stats["output_tokens"],
        "total_tokens": llm_stats["total_tokens"],
        "cost_usd": float(llm_stats["cost_usd"]),
        "llm_duration_ms": float(
            llm_stats["llm_duration_ms"]
        ),
    }


@router.get("/models")
def get_model_breakdown() -> list[dict]:
    query = """
        SELECT
            COALESCE(
                payload->>'actual_model',
                payload->>'model',
                name
            ) AS model,

            COALESCE(
                payload->>'provider',
                'unknown'
            ) AS provider,

            COUNT(*) AS calls,

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
                AVG(duration_ms) FILTER (
                    WHERE duration_ms IS NOT NULL
                ),
                0
            ) AS avg_duration_ms,

            COALESCE(
                SUM((payload->>'cost_usd')::NUMERIC),
                0
            ) AS cost_usd

        FROM spans

        WHERE span_type = 'llm'

        GROUP BY
            COALESCE(
                payload->>'actual_model',
                payload->>'model',
                name
            ),
            COALESCE(
                payload->>'provider',
                'unknown'
            )

        ORDER BY calls DESC, total_tokens DESC
    """

    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row
        ) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

    return [
        {
            "model": row["model"],
            "provider": row["provider"],
            "calls": row["calls"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "total_tokens": row["total_tokens"],
            "avg_duration_ms": float(
                row["avg_duration_ms"]
            ),
            "cost_usd": float(
                row["cost_usd"]
            ),
        }
        for row in rows
    ]



@router.get("/failures")
def get_failure_analytics() -> dict:
    summary_query = """
        SELECT
            (SELECT COUNT(*)
             FROM traces)
                AS total_runs,

            (SELECT COUNT(*)
             FROM traces
             WHERE status = 'error')
                AS failed_runs,

            (SELECT COUNT(*)
             FROM spans
             WHERE status = 'error')
                AS failed_spans,

            (
                SELECT COUNT(DISTINCT trace_id)
                FROM spans
                WHERE status = 'error'
            ) AS traces_with_span_failures,

            (
                SELECT COUNT(DISTINCT s.trace_id)
                FROM spans s
                JOIN traces t
                    ON t.trace_id = s.trace_id
                WHERE
                    s.status = 'error'
                    AND t.status = 'success'
            ) AS recovered_runs
    """

    by_type_query = """
        SELECT
            span_type,
            COUNT(*) AS failures
        FROM spans
        WHERE status = 'error'
        GROUP BY span_type
        ORDER BY failures DESC
    """

    by_name_query = """
        SELECT
            span_type,
            name,
            COUNT(*) AS failures
        FROM spans
        WHERE status = 'error'
        GROUP BY span_type, name
        ORDER BY failures DESC
    """

    with get_connection() as connection:
        with connection.cursor(
            row_factory=dict_row
        ) as cursor:

            cursor.execute(summary_query)
            summary = cursor.fetchone()

            cursor.execute(by_type_query)
            by_type = cursor.fetchall()

            cursor.execute(by_name_query)
            by_name = cursor.fetchall()

    total_runs = summary["total_runs"]
    failed_runs = summary["failed_runs"]

    failure_rate = (
        failed_runs / total_runs * 100
        if total_runs > 0
        else 0
    )

    return {
        "total_runs": total_runs,
        "failed_runs": failed_runs,
        "failure_rate": round(failure_rate, 2),
        "failed_spans": summary["failed_spans"],
        "traces_with_span_failures":
            summary["traces_with_span_failures"],
        "recovered_runs": summary["recovered_runs"],
        "by_span_type": by_type,
        "by_span_name": by_name,
    }


@router.get("/decisions")
def get_decision_analytics() -> dict:
    """
    Aggregate planner-decision analytics across all traces.

    This drives the overview "decision distribution" panel: how
    often each action is chosen by the planner, and how often each
    action is *offered but rejected*. The rejected-vs-chosen ratio
    is the enterprise wedge — it shows which tools the planner
    considers but avoids, which is exactly the "why did it decide
    this" signal that generic tracing platforms don't surface.
    """

    summary_query = """
        SELECT
            COUNT(*) AS total_decisions,
            COUNT(*) FILTER (WHERE status = 'error')
                AS error_decisions
        FROM spans
        WHERE span_type = 'planner'
    """

    # How many times each action was chosen.
    chosen_query = """
        SELECT
            payload->>'chosen_action' AS action,
            COUNT(*) AS chosen
        FROM spans
        WHERE span_type = 'planner'
          AND payload->>'chosen_action' IS NOT NULL
        GROUP BY payload->>'chosen_action'
    """

    # How many times each action appeared in the candidate set
    # (i.e. was offered to the planner). Unnesting the JSONB array
    # gives one row per (span, candidate).
    offered_query = """
        SELECT
            action::text AS action,
            COUNT(*) AS offered
        FROM spans,
             jsonb_array_elements_text(
                 payload->'candidates'
             ) AS action
        WHERE span_type = 'planner'
        GROUP BY action
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(summary_query)
            summary = cursor.fetchone()

            cursor.execute(chosen_query)
            chosen_rows = cursor.fetchall()

            cursor.execute(offered_query)
            offered_rows = cursor.fetchall()

    total_decisions = summary["total_decisions"]

    chosen_map = {
        row["action"]: row["chosen"] for row in chosen_rows
    }
    offered_map = {
        row["action"]: row["offered"] for row in offered_rows
    }

    # Distribution of chosen actions (for the bar chart).
    distribution = [
        {
            "action": action,
            "count": count,
            "pct": (
                round(count / total_decisions * 100, 1)
                if total_decisions > 0
                else 0
            ),
        }
        for action, count in sorted(
            chosen_map.items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    # Rejection stats: offered minus chosen per action.
    all_actions = set(offered_map) | set(chosen_map)
    rejection = [
        {
            "action": action,
            "offered": offered_map.get(action, 0),
            "chosen": chosen_map.get(action, 0),
            "rejected": offered_map.get(action, 0)
            - chosen_map.get(action, 0),
        }
        for action in all_actions
    ]
    rejection.sort(
        key=lambda r: r["rejected"], reverse=True
    )

    return {
        "total_decisions": total_decisions,
        "error_decisions": summary["error_decisions"],
        "distribution": distribution,
        "rejection": rejection,
    }


# Map a friendly bucket name to a Postgres interval. Kept as a
# closed whitelist so the interval string is never user-controlled
# raw input.
_BUCKET_INTERVALS = {
    "15m": "15 minutes",
    "hour": "1 hour",
    "day": "1 day",
}


@router.get("/cost-trend")
def get_cost_trend(
    bucket: str = "hour",
    limit: int = 48,
) -> dict:
    """
    Cost & token usage over time, bucketed.

    Returns a time series (oldest first) where each point is one
    bucket aggregating every trace that started inside it:
    run count, LLM calls, recorded cost, and input/output/total
    tokens. This drives the overview cost-trend chart.

    ``bucket`` is one of ``15m`` / ``hour`` / ``day``. ``limit``
    caps the number of buckets returned (most recent first, then
    reversed to oldest-first for charting).
    """

    interval = _BUCKET_INTERVALS.get(bucket)
    if interval is None:
        return {
            "bucket": bucket,
            "series": [],
            "error": (
                f"invalid bucket '{bucket}'; "
                "expected one of 15m, hour, day"
            ),
        }

    if limit < 1 or limit > 500:
        limit = 48

    query = """
        SELECT
            date_bin(
                %s::interval,
                t.started_at,
                '2000-01-01 00:00:00+00'::timestamptz
            ) AS bucket,

            COUNT(DISTINCT t.trace_id) AS runs,
            COUNT(s.span_id) AS llm_calls,

            COALESCE(
                SUM((s.payload->>'cost_usd')::NUMERIC), 0
            ) AS cost_usd,

            COALESCE(
                SUM((s.payload->>'input_tokens')::BIGINT), 0
            ) AS input_tokens,

            COALESCE(
                SUM((s.payload->>'output_tokens')::BIGINT), 0
            ) AS output_tokens,

            COALESCE(
                SUM((s.payload->>'total_tokens')::BIGINT), 0
            ) AS total_tokens

        FROM traces t
        LEFT JOIN spans s
            ON s.trace_id = t.trace_id
           AND s.span_type = 'llm'
        GROUP BY 1
        ORDER BY bucket DESC
        LIMIT %s
    """

    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, (interval, limit))
            rows = cursor.fetchall()

    # Reverse to oldest-first so the chart reads left-to-right.
    rows.reverse()

    series = [
        {
            "bucket": row["bucket"].isoformat(),
            "runs": row["runs"],
            "llm_calls": row["llm_calls"],
            "cost_usd": float(row["cost_usd"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "total_tokens": int(row["total_tokens"]),
        }
        for row in rows
    ]

    # Headline totals across the returned window.
    totals = {
        "runs": sum(p["runs"] for p in series),
        "llm_calls": sum(p["llm_calls"] for p in series),
        "cost_usd": round(
            sum(p["cost_usd"] for p in series), 6
        ),
        "input_tokens": int(
            sum(p["input_tokens"] for p in series)
        ),
        "output_tokens": int(
            sum(p["output_tokens"] for p in series)
        ),
        "total_tokens": int(
            sum(p["total_tokens"] for p in series)
        ),
    }

    return {
        "bucket": bucket,
        "series": series,
        "totals": totals,
    }