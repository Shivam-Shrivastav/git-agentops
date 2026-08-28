# Deploying AgentOps + the github-agent to a VPS

This is the **production** deployment: the full AgentOps observability
stack (PostgreSQL, Redis, ingestion API, worker, dashboard) **plus** the
github-agent wrapped as an HTTP service, behind Caddy with automatic
HTTPS and HTTP basic auth — all on one VPS via Docker Compose.

> Local development still uses `docker-compose.yml` (no Caddy, host ports
> mapped). This file only covers the production compose,
> `docker-compose.prod.yml`.

## Architecture

```
                 internet
                    │
              ┌─────┴─────┐   80/443   ┌───────┐
              │  Caddy    │ ─────────▶ │ Caddy │  auto-HTTPS (Let's Encrypt) + basicauth
              └─────┬─────┘            └───┬───┘
                    │  internal compose network
        ┌───────────┼───────────────────┬─────────────┐
        ▼           ▼                   ▼             ▼
   /api/* ─▶ ingestion-api:8000     /agent/* ─▶ agent-service:8001
                                              (runs the agent in-process,
                                               emits events to ingestion-api)
        ▼                                                  │
   dashboard:5173  (built SPA, calls same-origin /api)      ▼
                                                     ingestion-api:8000
        │
        ▼
   db (postgres) · redis · worker
```

Only Caddy is exposed to the host (ports 80/443). The ingestion API,
dashboard, and agent-service are **not** mapped to the host — they are
reachable only through Caddy over the internal compose network. The agent
emits its events directly to `http://ingestion-api:8000/events` (internal),
so it never crosses the public auth boundary.

## Prerequisites

- A VPS (Ubuntu 22.04+ recommended) reachable on ports 80 and 443.
- Docker Engine + the `docker compose` plugin installed on the VPS.
- A domain name you control, with an **A record** pointing at the VPS IP,
  e.g. `agentops.example.com.  A  203.0.113.10`. Caddy uses this to issue
  the TLS certificate, so DNS must resolve before you start Caddy.
- A GitHub personal access token (repo scope) and an OpenRouter API key.

## Steps

### 1. Get the code on the VPS

```bash
git clone <your-repo-url> agentops-prototype
cd agentops-prototype
```

### 2. Create the production `.env`

Copy the template and fill in the values:

```bash
cp .env.prod.example .env
$EDITOR .env
```

Set at minimum:

- `DOMAIN` — the domain pointing at this VPS.
- `AUTH_USER` — the basic-auth username (e.g. `admin`).
- `AUTH_HASH` — a bcrypt hash of the password (next step).
- `GITHUB_TOKEN`, `OPENROUTER_API_KEY` — agent secrets.

### 3. Generate the basic-auth password hash

Caddy's `basic_auth` needs a bcrypt hash, not the plaintext password. Use
the Caddy image itself to generate it:

```bash
docker compose -f docker-compose.prod.yml run --rm caddy \
  caddy hash-password --plaintext 'YOUR_PASSWORD'
```

The output starts with `$2a$…`. **Escape every `$` as `$$`** when you put it
in `.env` — compose otherwise expands `$2a`, `$14`, … as variable
references and corrupts the hash (auth then always 401s). This one-liner
generates the hash and writes the escaped `AUTH_HASH` line for you:

```bash
HASH=$(docker compose -f docker-compose.prod.yml run --rm caddy \
  caddy hash-password --plaintext 'YOUR_PASSWORD')
python3 -c "print('AUTH_HASH=' + __import__('sys').argv[1].replace('\$','\$\$'))" "$HASH" >> .env
```

(If you edit `.env` by hand instead, write e.g. `AUTH_HASH=$$2a$$14$$<rest>`.)

### 4. Build and start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

This builds the ingestion API, worker, dashboard (production SPA), and the
agent-service image, then starts everything. Caddy obtains a Let's
Encrypt certificate on first start (this takes a few seconds; watch with
`docker compose -f docker-compose.prod.yml logs -f caddy`).

### 5. Verify

- Open `https://<DOMAIN>` in a browser. You will be prompted for the
  basic-auth credentials. The dashboard should load and show traces.
- Health check through Caddy:
  ```bash
  curl -u admin:YOUR_PASSWORD https://<DOMAIN>/api/health
  # {"status":"ok"}
  ```

### 6. Trigger an agent run

The agent is exposed at `/agent`. A `POST /run` starts the agent in the
background and returns a `run_id`; poll `GET /runs/{run_id}` for the
`trace_id` (link it to a trace in the dashboard) and final response.

```bash
# Start a read-only run (no clarifications needed):
curl -u admin:YOUR_PASSWORD -X POST https://<DOMAIN>/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"list open issues in Shivam-Shrivastav/Data-Structures"}'
# {"run_id":"...","status":"started",...}

# Poll for the result (the free model can take 1–3 minutes):
curl -u admin:YOUR_PASSWORD https://<DOMAIN>/agent/runs/<run_id>
# {"run_id":"...","status":"done","trace_id":"...","final_response":"...",...}
```

If the agent needs more input, the run ends with `status:"needs_input"`
and a `question`. Supply clarifications up front so the run completes in
one shot:

```bash
curl -u admin:YOUR_PASSWORD -X POST https://<DOMAIN>/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"add a comment to issue #4 in Shivam-Shrivastav/Data-Structures",
       "clarifications":["issue number 4"]}'
```

The agent's events flow to the ingestion API and appear in the dashboard
trace view (including the Decision Quality panel when
`AGENT_DECISION_JUDGE=1` and the judge span succeeds).

## Operations

- **Rebuild after code changes:**
  `docker compose -f docker-compose.prod.yml up -d --build`
- **Logs:**
  `docker compose -f docker-compose.prod.yml logs -f caddy`
  `docker compose -f docker-compose.prod.yml logs -f agent-service`
- **Shell in the agent service:**
  `docker compose -f docker-compose.prod.yml exec agent-service sh`
- **Inspect the DB:**
  `docker compose -f docker-compose.prod.yml exec db psql -U agentops -d agentops`
- **Renewals:** Caddy renews certificates automatically; nothing to do.
- **Teardown:** `docker compose -f docker-compose.prod.yml down`
  (add `-v` to also delete the DB and Caddy data volumes).

## Notes

- **Auth:** HTTP basic auth (via Caddy) is the only public gate. The
  ingestion API itself has no auth — it is not exposed to the host. If you
  later need remote (non-VPS) agents to emit over the public API, add a
  Bearer check on the ingestion API (the SDK already sends
  `Authorization: Bearer $AGENTOPS_API_KEY`) and exempt `/api/events`
  from basicauth in the `Caddyfile`.
- **Agent behaviour knobs** (`AGENT_DESTRUCTIVE_ACTION_POLICY`,
  `AGENT_MAX_TOTAL_TOKENS`, `AGENT_DECISION_JUDGE`, `AGENT_MAX_STEPS`) are
  set in `.env` and read by the agent-service. `confirm` prompts for
  approval interactively, which the HTTP service cannot satisfy — use
  `allow` or `deny` for hosted runs.
- **Single replica:** the agent-service holds run state in memory; one
  replica is sufficient for a prototype. Scale-out would need shared state
  (Redis) and a job queue.
- **Free OpenRouter model** is flaky; a run may occasionally error or
  loop. Re-trigger the run, or set `OPENROUTER_MODEL` to a paid model.