"""Shared base for every simple agent.

Provides:
- AgentOps tracing setup (console + HTTP emitter)
- A simple OpenAI-compatible LLM helper instrumented as an `llm` span
- A uniform `run(task)` contract that returns status + trace_id
- Optional LLM-judge decision-quality evaluation (AGENT_DECISION_JUDGE=1)
"""
from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agentops import AgentOps
from agentops.emitter import ConsoleEmitter, HTTPEmitter


load_dotenv()


def _client() -> AsyncOpenAI:
    """Build an async OpenAI-compatible client from environment.

    Reads ``LLM_BASE_URL`` / ``LLM_API_KEY`` first, then falls back to the
    legacy ``OPENROUTER_*`` variables. This lets simple-agents point at a
    local Ollama instance (e.g. ``http://localhost:11434/v1`` or
    ``http://host.docker.internal:11434/v1`` from Docker) while keeping
    the existing github-agent config untouched.
    """
    base_url = os.getenv(
        "LLM_BASE_URL",
        os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    ).rstrip("/")
    api_key = os.getenv(
        "LLM_API_KEY",
        os.getenv("OPENROUTER_API_KEY", ""),
    ).strip()

    # Ollama's OpenAI-compatible endpoint does not require an API key.
    is_local_ollama = any(
        host in base_url
        for host in ("localhost:11434", "127.0.0.1:11434", "host.docker.internal:11434")
    )
    if not api_key and not is_local_ollama:
        raise ValueError(
            "Missing LLM_API_KEY / OPENROUTER_API_KEY. Add it to your environment "
            "or .env file, or point LLM_BASE_URL at a local Ollama endpoint."
        )

    return AsyncOpenAI(base_url=base_url, api_key=api_key or "ollama")


class BaseAgent(ABC):
    """All simple agents inherit from this base.

    Subclasses must implement:
        name: str            # unique agent id
        display_name: str    # human label shown in the UI
        description: str     # one-line summary
        async def execute(self, task: str, clarifications: list[str]) -> str

    The base class handles trace creation, LLM instrumentation, and the
    common result envelope.
    """

    name: str = "base"
    display_name: str = "Base Agent"
    description: str = ""

    def __init__(self) -> None:
        self.client = _client()
        self.model = os.getenv(
            "LLM_MODEL",
            os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        ).strip()
        self.http_referer = os.getenv(
            "LLM_HTTP_REFERER",
            os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost"),
        ).strip()
        self.app_name = os.getenv(
            "LLM_APP_NAME",
            os.getenv("OPENROUTER_APP_NAME", "simple-agents"),
        ).strip()
        # Record the actual provider for the trace.
        self.provider = (
            "Ollama" if "11434" in self.client.base_url.host else "OpenRouter"
        )

        self.ops = AgentOps(
            emitters=[
                ConsoleEmitter(),
                HTTPEmitter(
                    endpoint=os.getenv(
                        "AGENTOPS_ENDPOINT",
                        "http://127.0.0.1:8000/events",
                    ),
                ),
            ]
        )
        self._decisions: list[dict[str, Any]] = []

    async def _llm_chat(
        self,
        system: str,
        user: str,
        *,
        name: str = "llm",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Call the LLM asynchronously and record it as an `llm` span."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        with self.ops.llm(
            name=name,
            provider=self.provider,
            model=self.model,
        ) as llm_span:
            llm_span.set_prompts(system=system, user=user)
            llm_span.set_params(temperature=temperature)
            if max_tokens is not None:
                llm_span.set_params(max_tokens=max_tokens)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": self.http_referer,
                    "X-Title": self.app_name,
                },
            )

            content = response.choices[0].message.content or ""
            usage = response.usage

            # OpenAI-compatible providers use prompt_tokens/completion_tokens;
            # some newer APIs use input_tokens/output_tokens. Support both.
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            if input_tokens is None and usage:
                input_tokens = getattr(usage, "prompt_tokens", None)
            if output_tokens is None and usage:
                output_tokens = getattr(usage, "completion_tokens", None)

            llm_span.set_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            llm_span.set_response_metadata(
                actual_model=response.model,
                finish_reason=response.choices[0].finish_reason,
            )
            llm_span.set_completion(text=content)

            return content

    async def _tool(self, name: str, args: dict[str, Any]) -> Any:
        """Convenience wrapper: execute a function inside an ops.tool span."""
        import asyncio
        import inspect

        method = getattr(self, f"_tool_{name}", None)
        if method is None:
            raise ValueError(f"Unknown tool '{name}' on {self.name}")

        with self.ops.tool(name=name, **args) as tool_span:
            result = method(**args)
            if inspect.iscoroutine(result):
                result = await result
            tool_span.set_result(return_value=result)
            return result

    def _planner_decision(
        self,
        *,
        thought: str,
        chosen_action: str,
        candidates: list[str] | None = None,
        rejected_actions: list[str] | None = None,
        confidence: float | None = None,
        iteration: int | None = None,
        **extra: Any,
    ) -> None:
        """Emit a planner decision span so the dashboard timeline can render it.

        This is a synchronous, one-shot span. The simple agents reason inside
        LLM calls; this helper captures the outcome of that reasoning as a
        decision the dashboard can inspect.
        """
        decision = {
            "thought": thought,
            "chosen_action": chosen_action,
            "candidates": candidates,
            "rejected_actions": rejected_actions,
            "confidence": confidence,
            "iteration": iteration,
            **extra,
        }
        self._decisions.append(decision)

        with self.ops.planner(model=self.model) as planner_span:
            planner_span.set_plan(
                thought=thought,
                chosen_action=chosen_action,
                candidates=candidates,
                rejected_actions=rejected_actions,
                confidence=confidence,
                iteration=iteration,
            )
            if extra:
                planner_span.set_params(**extra)

    async def _evaluate_decisions(self, task: str, final_response: str) -> dict[str, Any] | None:
        """Run an optional LLM-judge decision-quality evaluation.

        Enabled when ``AGENT_DECISION_JUDGE=1``. The judge scores the agent's
        planner decisions on relevance, efficiency, and correctness and stores
        the result in a ``decision-quality-judge`` LLM span so the dashboard's
        Decision Quality panel can display it.
        """
        if os.getenv("AGENT_DECISION_JUDGE", "0") != "1":
            return None

        if not self._decisions:
            return None

        transcript_lines: list[str] = []
        for i, step in enumerate(self._decisions, 1):
            action = step.get("chosen_action", "")
            thought = step.get("thought", "")
            candidates = step.get("candidates") or []
            rejected = step.get("rejected_actions") or []
            confidence = step.get("confidence")
            line = f"Step {i}: action={action} thought={thought!r} candidates={candidates} rejected={rejected}"
            if confidence is not None:
                line += f" confidence={confidence}"
            transcript_lines.append(line)
        transcript = "\n".join(transcript_lines)

        system = (
            "You are a strict evaluator scoring an AI agent's decision-making. "
            "Given the user's task, the agent's planner decisions (each with the "
            "agent's stated thought, the action it chose, the alternatives it rejected, "
            "and its confidence), and the final response, rate the quality of the "
            "decisions on relevance, efficiency, and correctness. Respond with valid "
            "JSON only, no markdown fences:\n"
            '{"score": <integer 1-5>, '
            '"summary": "<one sentence>", '
            '"strengths": ["...", "..."], '
            '"weaknesses": ["...", "..."]}'
        )
        user = (
            f"Task: {task}\n\n"
            f"Final response:\n{final_response[:2000]}\n\n"
            f"Decisions:\n{transcript}\n\n"
            "Return the JSON evaluation."
        )

        with self.ops.llm(
            name="decision-quality-judge",
            provider=self.provider,
            model=self.model,
        ) as judge_span:
            judge_span.set_prompts(system=system, user=user)
            judge_span.set_params(temperature=0)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                extra_headers={
                    "HTTP-Referer": self.http_referer,
                    "X-Title": self.app_name,
                },
            )

            content = response.choices[0].message.content or ""
            usage = response.usage

            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            if input_tokens is None and usage:
                input_tokens = getattr(usage, "prompt_tokens", None)
            if output_tokens is None and usage:
                output_tokens = getattr(usage, "completion_tokens", None)

            judge_span.set_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            judge_span.set_response_metadata(
                actual_model=response.model,
                finish_reason=response.choices[0].finish_reason,
            )
            judge_span.set_completion(text=content)

            parsed = self._extract_json_safe(content)
            if parsed:
                judge_span.set_params(
                    eval_score=parsed.get("score"),
                    eval_summary=parsed.get("summary"),
                    eval_strengths=parsed.get("strengths"),
                    eval_weaknesses=parsed.get("weaknesses"),
                )
                return parsed
            return None

    def _extract_json_safe(self, text: str) -> Any | None:
        """Extract JSON from an LLM response, tolerating markdown fences."""
        import json

        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except Exception:
            return None

    @abstractmethod
    async def execute(self, task: str, clarifications: list[str]) -> str:
        """Run the agent. Must return the final response string."""
        ...

    async def run(
        self,
        task: str,
        clarifications: list[str] | None = None,
    ) -> dict[str, Any]:
        """Entry point used by the HTTP service.

        Returns a dict with keys:
            status, final_response, trace_id, needs_input, failed
        """
        clarifications = clarifications or []
        self._decisions = []

        with self.ops.trace(
            self.name,
            payload={
                "task": task,
                "user_query": task,
                "session_id": str(uuid.uuid4()),
                "agent_name": self.name,
                "agent_display_name": self.display_name,
                "agent_version": "0.1.0",
                "framework": "simple-agents",
            },
        ) as trace:
            trace_id = self.ops.context.current().trace_id

            # Wrap the actual agent execution in a generic span so all LLM,
            # tool and planner calls inside execute() become nested children
            # and the dashboard renders a real execution tree.
            with self.ops.span(
                name="execute",
                payload={"agent_name": self.name},
            ):
                try:
                    final_response = await self.execute(task, clarifications)
                    failed = False
                    status = "done"
                    needs_input = False
                except Exception as exc:
                    trace.set_error(
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        failure_stage="agent",
                    )
                    final_response = f"The agent failed: {exc}"
                    failed = True
                    status = "error"
                    needs_input = False

            # Optional LLM-judge decision-quality evaluation. Run inside the
            # active trace so the judge's LLM span is properly parented.
            if os.getenv("AGENT_DECISION_JUDGE", "0") == "1":
                try:
                    await self._evaluate_decisions(task, final_response)
                except Exception:
                    # The judge must never fail the run.
                    pass

        return {
            "status": status,
            "final_response": final_response,
            "trace_id": trace_id,
            "needs_input": needs_input,
            "failed": failed,
        }
