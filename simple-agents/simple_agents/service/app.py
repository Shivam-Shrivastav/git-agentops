"""HTTP service wrapper around the simple agents.

Mirrors the github-agent service contract:
    GET  /health            -> {"status": "ok"}
    POST /run               -> 202 {"run_id", "status": "started", "task"}
    GET  /runs/{run_id}     -> {"run_id", "trace_id?", "status", "final_response?"}

The request body includes an `agent` field to pick which simple agent runs.
"""
from __future__ import annotations

import asyncio
import threading
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from simple_agents.diff_summarizer import DiffSummarizerAgent
from simple_agents.json_wrangler import JSONWranglerAgent
from simple_agents.local_researcher import LocalResearcherAgent
from simple_agents.share_page import SharePageAgent
from simple_agents.trade_signal import TradeSignalAgent
from simple_agents.trip_planner import TripPlannerAgent

app = FastAPI(title="simple-agents service")

# Allow the dashboard (local Vite dev or production origin) to call this
# service from the browser. In production Caddy proxies same-origin, but
# local dev serves the dashboard on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# agent_id -> builder. Each agent is instantiated per run so trace context is fresh.
_AGENT_REGISTRY: dict[str, tuple[str, type]] = {
    TripPlannerAgent.name: (TripPlannerAgent.display_name, TripPlannerAgent),
    LocalResearcherAgent.name: (LocalResearcherAgent.display_name, LocalResearcherAgent),
    JSONWranglerAgent.name: (JSONWranglerAgent.display_name, JSONWranglerAgent),
    DiffSummarizerAgent.name: (DiffSummarizerAgent.display_name, DiffSummarizerAgent),
    SharePageAgent.name: (SharePageAgent.display_name, SharePageAgent),
    TradeSignalAgent.name: (TradeSignalAgent.display_name, TradeSignalAgent),
}

_runs: dict[str, dict[str, Any]] = {}
_runs_lock = threading.Lock()


class RunRequest(BaseModel):
    agent: str
    task: str
    clarifications: list[str] = []


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agents")
def list_agents() -> list[dict[str, str]]:
    """Return the available simple agents for the dashboard selector."""
    return [
        {"id": agent_id, "name": display_name}
        for agent_id, (display_name, _) in _AGENT_REGISTRY.items()
    ]


@app.post("/run", status_code=202)
def run_agent(req: RunRequest) -> dict[str, Any]:
    if req.agent not in _AGENT_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{req.agent}'. Available: {', '.join(_AGENT_REGISTRY)}",
        )

    run_id = str(uuid.uuid4())
    with _runs_lock:
        _runs[run_id] = {
            "run_id": run_id,
            "status": "running",
            "task": req.task,
            "agent": req.agent,
        }

    thread = threading.Thread(
        target=_run_in_thread,
        args=(run_id, req.agent, req.task, req.clarifications),
        name=f"simple-agent-run-{run_id[:8]}",
        daemon=True,
    )
    thread.start()

    return {"run_id": run_id, "status": "started", "task": req.task, "agent": req.agent}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        return {"run_id": run_id, "status": "not_found"}
    return run


def _run_in_thread(
    run_id: str,
    agent_id: str,
    task: str,
    clarifications: list[str],
) -> None:
    """Run the async agent in a fresh event loop inside a background thread."""
    _, agent_cls = _AGENT_REGISTRY[agent_id]
    agent = agent_cls()

    try:
        result = asyncio.run(agent.run(task, clarifications))

        with _runs_lock:
            _runs[run_id].update(
                {
                    "status": result.get("status", "done"),
                    "trace_id": result.get("trace_id"),
                    "final_response": result.get("final_response"),
                    "failed": bool(result.get("failed", False)),
                    "needs_input": bool(result.get("needs_input", False)),
                }
            )
    except Exception as exc:  # noqa: BLE001
        with _runs_lock:
            _runs[run_id].update(
                {
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
