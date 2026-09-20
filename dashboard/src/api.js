// Base URL for the ingestion API.
//
// In local dev (vite dev server, no reverse proxy) this resolves to the
// host's ingestion-api at http://localhost:8000. In production the app is
// served behind a reverse proxy (Caddy) that mounts the API at /api, so the
// build passes VITE_API_BASE_URL=/api and the browser calls the same origin.
const API_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// The github-agent HTTP service is mounted at /agent/* by the reverse proxy
// (a different prefix from the ingestion API's /api/*), so it gets its own
// base URL. In production both are same-origin behind Caddy; the build passes
// VITE_AGENT_BASE_URL=/agent. Local dev has no agent-service, so the panel is
// a hosted-deployment feature (calls fail gracefully there).
const AGENT_URL =
  import.meta.env.VITE_AGENT_BASE_URL ?? "/agent";

// The simple-agents service is mounted at /simple-agent/* by the reverse
// proxy. It exposes six lightweight agents for the dashboard playground.
const SIMPLE_AGENT_URL =
  import.meta.env.VITE_SIMPLE_AGENT_BASE_URL ?? "/simple-agent";


// Centralised fetch wrapper. All API calls go through here so there is a
// single place that knows the base URL, method, and error handling.
async function request(path, { method = "GET", body } = {}) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_URL}${path}`, init);

  if (!response.ok) {
    let message = `API returned ${response.status}`;
    try {
      const responseBody = await response.json();
      if (responseBody.detail) {
        message = responseBody.detail;
      }
    } catch {
      // Response wasn't JSON.
    }
    throw new Error(message);
  }

  return response.json();
}


export function getTraces(limit = 50) {
  return request(`/traces?limit=${limit}`);
}


export function getTraceTree(traceId) {
  return request(`/traces/${encodeURIComponent(traceId)}/tree`);
}

export function getTraceUsage(traceId) {
  return request(`/traces/${encodeURIComponent(traceId)}/usage`);
}

export function getOverview() {
  return request(`/analytics/overview`);
}

export function getModelBreakdown() {
  return request(`/analytics/models`);
}

export function getFailureAnalytics() {
  return request(`/analytics/failures`);
}

export function getTraceError(traceId) {
  return request(`/traces/${encodeURIComponent(traceId)}/error`);
}

export function getTraceDecisions(traceId) {
  return request(`/traces/${encodeURIComponent(traceId)}/decisions`);
}

export function getTraceDecisionQuality(traceId) {
  return request(`/traces/${encodeURIComponent(traceId)}/decision-quality`);
}

export function getDecisionAnalytics() {
  return request(`/analytics/decisions`);
}

export function getCostTrend(bucket = "hour", limit = 48) {
  return request(
    `/analytics/cost-trend?bucket=${encodeURIComponent(bucket)}&limit=${limit}`
  );
}

export function getSpans({
  span_type,
  status,
  name,
  chosen_action,
  trace_id,
  limit = 50,
} = {}) {
  const params = new URLSearchParams();

  if (span_type) params.set("span_type", span_type);
  if (status) params.set("status", status);
  if (name) params.set("name", name);
  if (chosen_action) params.set("chosen_action", chosen_action);
  if (trace_id) params.set("trace_id", trace_id);
  params.set("limit", String(limit));

  return request(`/spans?${params.toString()}`);
}

export function getAlertRules() {
  return request(`/alerts/rules`);
}

export function upsertAlertRule(rule) {
  return request(`/alerts/rules`, { method: "POST", body: rule });
}

export function deleteAlertRule(ruleId) {
  return request(`/alerts/rules/${encodeURIComponent(ruleId)}`, {
    method: "DELETE",
  });
}

export function evaluateAlerts() {
  return request(`/alerts/evaluate`);
}


// ---- Agent service (github-agent HTTP wrapper at /agent) -----------------
// The browser carries the cached Caddy basic-auth credentials on these
// same-origin fetches, so no explicit Authorization header is needed.

async function agentRequest(path, { method = "GET", body } = {}) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  const response = await fetch(`${AGENT_URL}${path}`, init);

  if (!response.ok) {
    let message = `Agent service returned ${response.status}`;
    try {
      const responseBody = await response.json();
      if (responseBody.detail) {
        message = responseBody.detail;
      }
    } catch {
      // Response wasn't JSON.
    }
    throw new Error(message);
  }

  return response.json();
}


// Start a run; returns 202 { run_id, status: "started", task }.
export function startAgentRun(task, clarifications = []) {
  return agentRequest(`/run`, {
    method: "POST",
    body: { task, clarifications },
  });
}


// Poll a run; shape depends on status:
//   running     -> { run_id, status, task }
//   done        -> { run_id, status, trace_id, final_response, failed }
//   needs_input -> { run_id, status, trace_id, final_response, question, missing_inputs }
//   error       -> { run_id, status, error, traceback }
export function getAgentRun(runId) {
  return agentRequest(`/runs/${encodeURIComponent(runId)}`);
}


// ---- Simple agents service (lightweight playground agents) ---------------

async function simpleAgentRequest(path, { method = "GET", body } = {}) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  const response = await fetch(`${SIMPLE_AGENT_URL}${path}`, init);

  if (!response.ok) {
    let message = `Simple agent service returned ${response.status}`;
    try {
      const responseBody = await response.json();
      if (responseBody.detail) {
        message = responseBody.detail;
      }
    } catch {
      // Response wasn't JSON.
    }
    throw new Error(message);
  }

  return response.json();
}


// List available simple agents for the selector.
export function getSimpleAgents() {
  return simpleAgentRequest(`/agents`);
}


// Start a simple agent run; returns 202 { run_id, status: "started" }.
export function startSimpleAgentRun(agent, task, clarifications = []) {
  return simpleAgentRequest(`/run`, {
    method: "POST",
    body: { agent, task, clarifications },
  });
}


// Poll a simple agent run; same shape as getAgentRun.
export function getSimpleAgentRun(runId) {
  return simpleAgentRequest(`/runs/${encodeURIComponent(runId)}`);
}
