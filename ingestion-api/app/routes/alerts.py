from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from psycopg.rows import dict_row

from app.database import get_connection


router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
)


# Kinds we know how to evaluate. Anything else in the table is
# returned as "unknown" and skipped during evaluation.
_KNOWN_KINDS = {
    "error_rate",
    "planner_failures",
    "tool_failures",
    "consecutive_failures",
}


class RuleIn(BaseModel):
    rule_id: str
    name: str
    kind: str
    threshold: float
    window_minutes: int = 15
    severity: str = "warning"
    enabled: bool = True


@router.get("/rules")
def list_rules() -> list[dict]:
    query = """
        SELECT
            rule_id,
            name,
            kind,
            threshold,
            window_minutes,
            severity,
            enabled
        FROM alert_rules
        ORDER BY severity = 'critical' DESC,
                 rule_id
    """
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query)
            return cursor.fetchall()


@router.post("/rules")
def upsert_rule(rule: RuleIn) -> dict:
    """
    Create or update a rule by rule_id (idempotent upsert).
    Used by the dashboard to tweak thresholds/windows live.
    """
    if rule.kind not in _KNOWN_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown kind '{rule.kind}'; expected one of "
                f"{', '.join(sorted(_KNOWN_KINDS))}"
            ),
        )

    query = """
        INSERT INTO alert_rules
            (rule_id, name, kind, threshold,
             window_minutes, severity, enabled)
        VALUES (%(rule_id)s, %(name)s, %(kind)s, %(threshold)s,
                %(window_minutes)s, %(severity)s, %(enabled)s)
        ON CONFLICT (rule_id) DO UPDATE SET
            name            = EXCLUDED.name,
            kind            = EXCLUDED.kind,
            threshold       = EXCLUDED.threshold,
            window_minutes  = EXCLUDED.window_minutes,
            severity        = EXCLUDED.severity,
            enabled         = EXCLUDED.enabled
        RETURNING rule_id, name, kind, threshold,
                  window_minutes, severity, enabled
    """
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, rule.model_dump())
            row = cursor.fetchone()

    return row


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str) -> dict:
    query = "DELETE FROM alert_rules WHERE rule_id = %s"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (rule_id,))
            deleted = cursor.rowcount
    return {"rule_id": rule_id, "deleted": deleted > 0}


@router.get("/evaluate")
def evaluate_alerts() -> dict:
    """
    Evaluate every enabled rule against current data and return
    each rule's state (firing / ok) plus the value that triggered it.

    State is derived on demand from a sliding window ending now,
    so there is no persisted alert-state table to drift out of sync.
    """
    query = """
        SELECT rule_id, name, kind, threshold,
               window_minutes, severity
        FROM alert_rules
        WHERE enabled
    """
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query)
            rules = cursor.fetchall()

            results = [
                _evaluate_rule(cursor, rule) for rule in rules
            ]

    firing = [r for r in results if r["state"] == "firing"]

    return {
        "firing_count": len(firing),
        "rules": results,
    }


def _evaluate_rule(cursor, rule: dict) -> dict:
    kind = rule["kind"]
    threshold = float(rule["threshold"])
    window = int(rule["window_minutes"])

    if kind == "error_rate":
        value, detail = _eval_error_rate(cursor, window)
        firing = value >= threshold
        message = (
            f"Trace error rate is {value:.1f}% over the last "
            f"{window}m (threshold {threshold:.0f}%)."
        )

    elif kind in ("planner_failures", "tool_failures"):
        span_type = (
            "planner" if kind == "planner_failures" else "tool"
        )
        value, detail = _eval_span_failures(
            cursor, window, span_type
        )
        firing = value >= threshold
        message = (
            f"{value} failed {span_type} span(s) in the last "
            f"{window}m (threshold {threshold:.0f})."
        )

    elif kind == "consecutive_failures":
        value, detail = _eval_consecutive(cursor, threshold, window)
        firing = value >= threshold
        message = (
            f"{value} consecutive failed run(s) "
            f"(threshold {threshold:.0f})."
        )

    else:
        value, detail, firing = 0, None, False
        message = f"Unknown kind '{kind}'."

    return {
        "rule_id": rule["rule_id"],
        "name": rule["name"],
        "kind": kind,
        "severity": rule["severity"],
        "threshold": threshold,
        "window_minutes": window,
        "current_value": round(value, 2) if value != int(value) else int(value),
        "state": "firing" if firing else "ok",
        "message": message,
        **(detail or {}),
    }


def _eval_error_rate(cursor, window: int) -> tuple:
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'error') AS failed
        FROM traces
        WHERE started_at >= NOW() - (%s || ' minutes')::interval
        """,
        (window,),
    )
    row = cursor.fetchone()
    total = row["total"]
    failed = row["failed"]
    rate = (failed / total * 100) if total > 0 else 0
    return rate, {"runs_in_window": total, "failed_in_window": failed}


def _eval_span_failures(cursor, window: int, span_type: str) -> tuple:
    cursor.execute(
        """
        SELECT COUNT(*) AS c
        FROM spans
        WHERE span_type = %s
          AND status = 'error'
          AND started_at >= NOW() - (%s || ' minutes')::interval
        """,
        (span_type, window),
    )
    row = cursor.fetchone()
    return row["c"], {"span_type": span_type}


def _eval_consecutive(cursor, threshold: float, window: int):
    # Look at the most recent `threshold` runs within the window
    # and count how many consecutive errors sit at the tail.
    cursor.execute(
        """
        SELECT status
        FROM traces
        WHERE started_at >= NOW() - (%s || ' minutes')::interval
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (window, int(threshold)),
    )
    statuses = [r["status"] for r in cursor.fetchall()]

    consecutive = 0
    for s in statuses:
        if s == "error":
            consecutive += 1
        else:
            break

    return consecutive, {"runs_checked": len(statuses)}