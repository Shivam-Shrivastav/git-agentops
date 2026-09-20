# Simple Agents

A collection of lightweight, privacy-safe agents built to plug into the AgentOps observability platform.

Each agent is instrumented with the same `agentops-sdk` used by `github-agent`, so every run produces a full trace in the dashboard.

## Agents

| Agent | What it does | External auth |
|-------|--------------|---------------|
| `weather-math-agent` | Parses a question, runs `calculate` and/or `weather` tools | None |
| `local-researcher-agent` | Searches DuckDuckGo, fetches pages, writes a cited report | None |
| `code-reviewer-agent` | Reviews pasted code for bugs/style/refactor suggestions | None |
| `share-page-agent` | Fetches a URL, summarizes it, shortens it, and makes a QR code | None |
| `eli5-quizmaster-agent` | Explains a topic simply and runs a short quiz | None |
| `color-creative-agent` | Generates a color palette from a mood/brand description | None |

## Configuration

Copy `.env.prod.example` (or the main repo `.env`) and set at least:

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openrouter/free
```

The service emits events to the ingestion API over the internal compose network via `AGENTOPS_ENDPOINT`.

### Using a local Ollama model (e.g. `minimax-m3:cloud`)

No OpenRouter key is required when pointing at a local Ollama endpoint:

```env
OPENROUTER_BASE_URL=http://host.docker.internal:11434/v1
OPENROUTER_MODEL=minimax-m3:cloud
OPENROUTER_API_KEY=ollama   # any non-empty string; Ollama ignores it
```

When running the service outside Docker, use `http://localhost:11434/v1`.

## Running locally

```bash
docker compose up --build
```

In local dev the simple-agent-service is exposed on `http://localhost:8002`. In production it is mounted at `/simple-agent/*` by Caddy and reached same-origin from the dashboard. The dashboard chat UI routes simple-agent runs here automatically.
