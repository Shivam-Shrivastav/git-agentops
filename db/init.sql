-- AgentOps — initial schema
--
-- This is the single source of truth for the database schema.
-- It is idempotent (CREATE TABLE IF NOT EXISTS) so it is safe to
-- run repeatedly. docker-compose mounts this file into
-- /docker-entrypoint-initdb.d/ so a fresh `postgres` container
-- initialises the schema automatically on first boot.
--
-- Design notes:
--   * payload columns are JSONB so any LLM/tool/planner metadata
--     is queryable (payload->>'key') without schema migrations.
--   * span_type / status are TEXT (not enums) so new span kinds
--     (retrieval, embedding, ...) and statuses can be added without
--     ALTER TYPE. A CHECK could be added later once the set freezes.
--   * No foreign keys are declared deliberately: the projection
--     layer is built to tolerate out-of-order and replayed events
--     (ON CONFLICT DO NOTHING + UPDATE ... WHERE). A strict FK would
--     turn a recoverable replay (e.g. a span.start arriving before
--     its agent.start) into a hard failure. FKs can be added once
--     ordering guarantees are tightened.
--   * GIN index on spans.payload supports jsonb containment (`@>`)
--     queries; equality on a single key (`payload->>'k' = v`) would
--     need an expression index — added later when analytics demands it.


CREATE TABLE IF NOT EXISTS traces (
    trace_id        TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    duration_ms     DOUBLE PRECISION,
    error_type      TEXT,
    error_message   TEXT,
    failure_stage   TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_started_at
    ON traces (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_traces_status
    ON traces (status);


CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT        PRIMARY KEY,
    trace_id        TEXT        NOT NULL,
    parent_span_id  TEXT,
    span_type       TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,
    duration_ms     DOUBLE PRECISION,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id
    ON spans (trace_id);

CREATE INDEX IF NOT EXISTS idx_spans_trace_started
    ON spans (trace_id, started_at);

CREATE INDEX IF NOT EXISTS idx_spans_span_type
    ON spans (span_type);

CREATE INDEX IF NOT EXISTS idx_spans_status
    ON spans (status);

-- Supports jsonb containment queries (@>). Use jsonb_path_ops for a
-- smaller, faster index when only @> is needed.
CREATE INDEX IF NOT EXISTS idx_spans_payload_gin
    ON spans USING GIN (payload jsonb_path_ops);


CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT        PRIMARY KEY,
    trace_id        TEXT        NOT NULL,
    span_id         TEXT        NOT NULL,
    parent_span_id  TEXT,
    timestamp       TIMESTAMPTZ NOT NULL,
    event_type      TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'success',
    duration_ms     DOUBLE PRECISION,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_trace_id
    ON events (trace_id);

CREATE INDEX IF NOT EXISTS idx_events_span_id
    ON events (span_id);

CREATE INDEX IF NOT EXISTS idx_events_event_type
    ON events (event_type);

CREATE INDEX IF NOT EXISTS idx_events_timestamp
    ON events (timestamp DESC);

-- ============================================================
-- Alert rules (Failure-alert slice)
-- Configurable rules evaluated against a sliding time window.
-- State (firing/ok) is derived on demand from current data, so
-- no alert-state table is needed at this stage.
-- ============================================================

CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id         TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    kind            TEXT        NOT NULL,
    threshold       NUMERIC     NOT NULL,
    window_minutes  INT         NOT NULL DEFAULT 15,
    severity        TEXT        NOT NULL DEFAULT 'warning',
    enabled         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO alert_rules (rule_id, name, kind, threshold, window_minutes, severity) VALUES
  ('error_rate_spike',       'Error rate spike',        'error_rate',           50, 15, 'critical'),
  ('planner_failure_burst',  'Planner failure burst',   'planner_failures',      2, 15, 'warning'),
  ('tool_failure_burst',     'Tool failure burst',      'tool_failures',         3, 15, 'warning'),
  ('consecutive_failed_runs','Consecutive failed runs', 'consecutive_failures',  3, 60, 'critical')
ON CONFLICT (rule_id) DO NOTHING;
