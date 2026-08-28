"""HTTP service wrapper around the github-agent.

Exposes the LangGraph agent as a small REST API so it can be triggered
remotely (e.g. from the dashboard or a webhook) in a hosted deployment.
The agent runs in a background thread per request and emits its events to
the ingestion API over the internal compose network; the dashboard shows
the resulting trace live.

Endpoints:
    GET  /health            -> {"status": "ok"}
    POST /run               -> 202 {"run_id", "status": "started"}
    GET  /runs/{run_id}     -> {"run_id", "trace_id?", "status", "final_response?"}

Run state is held in memory (single replica). This is a prototype-grade
service: there is no auth here — the public edge (Caddy basicauth) gates
access; the agent emits internally, not through this surface's auth.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from github_agent.config import Settings
from github_agent.github_api import GitHubClient
from github_agent.graph import GitHubAgent
from github_agent.memory import (
    build_context_prefix,
    load_memory,
    save_memory,
    update_memory_from_result,
)

app = FastAPI(title="github-agent service")

# run_id -> run state. Updated from background threads; guarded by a lock
# so GET /runs/{run_id} never reads a half-written entry.
_runs: dict[str, dict[str, Any]] = {}
_runs_lock = threading.Lock()


class RunRequest(BaseModel):
    """Trigger an agent run.

    `clarifications` are fed in order, one per NEED_INPUT round, in place of
    the interactive `input("> ")` the CLI uses. If the agent asks for more
    input than clarifications provided, the run ends with status=needs_input.
    """

    task: str
    clarifications: list[str] = []


def _build_agent(settings: Settings) -> GitHubAgent:
    """Construct a GitHubAgent exactly as the CLI does (cli.py:104-114)."""
    client = GitHubClient(
        token=settings.github_token,
        base_url=settings.github_api_base_url,
    )
    return GitHubAgent(
        model_base_url=settings.openrouter_base_url,
        model_name=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        http_referer=settings.openrouter_http_referer,
        app_name=settings.openrouter_app_name,
        github_client=client,
        max_steps=settings.agent_max_steps,
        progress_callback=None,
    )


def _run_agent(run_id: str, task: str, clarifications: list[str]) -> None:
    """Execute the agent, mirroring the CLI's NEED_INPUT loop (cli.py:121-150)."""
    try:
        settings = Settings.from_env()
        agent = _build_agent(settings)
        memory = load_memory()
        task_text = build_context_prefix(memory) + task

        clarification_history: list[str] = []
        ci = 0
        result: dict[str, Any] = {}

        while True:
            result = agent.run(task_text, user_query=task)
            if not result.get("needs_input"):
                break

            if ci >= len(clarifications):
                # No more clarifications to feed; surface the question and stop.
                with _runs_lock:
                    _runs[run_id].update(
                        {
                            "status": "needs_input",
                            "trace_id": result.get("trace_id"),
                            "final_response": result.get("final_response"),
                            "question": result.get("question")
                            or result.get("final_response")
                            or "I need more information.",
                            "missing_inputs": result.get("missing_inputs", []),
                        }
                    )
                return

            question = result.get("question") or result.get("final_response") or "I need more information."
            user_reply = clarifications[ci]
            ci += 1

            clarification_history.append(
                f"Clarification round {ci}:\n"
                f"Agent asked: {question}\n"
                f"User answered: {user_reply}"
            )
            task_text = (
                build_context_prefix(memory)
                + task
                + "\n\n"
                + "\n\n".join(clarification_history)
            )

        updated_memory = update_memory_from_result(memory, result)
        if updated_memory != memory:
            save_memory(updated_memory)

        with _runs_lock:
            _runs[run_id].update(
                {
                    "status": "done",
                    "trace_id": result.get("trace_id"),
                    "final_response": result.get("final_response"),
                    "failed": bool(result.get("failed", False)),
                }
            )
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        with _runs_lock:
            _runs[run_id].update(
                {
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run", status_code=202)
def run_agent(req: RunRequest) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    with _runs_lock:
        _runs[run_id] = {"run_id": run_id, "status": "running", "task": req.task}

    thread = threading.Thread(
        target=_run_agent,
        args=(run_id, req.task, req.clarifications),
        name=f"agent-run-{run_id[:8]}",
        daemon=True,
    )
    thread.start()

    return {"run_id": run_id, "status": "started", "task": req.task}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        return {"run_id": run_id, "status": "not_found"}
    return run