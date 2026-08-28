from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Callable, Literal, TypedDict
from urllib import response

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from github_agent.github_api import GitHubAPIError, GitHubClient
from agentops import AgentOps
from agentops.emitter import ConsoleEmitter, HTTPEmitter

from github_agent.registry import (
    ACTION_REGISTRY,
    ActionDefinition,
    ActionRetriever,
    format_candidates_for_prompt,
    get_action_definition,
)


class AgentState(TypedDict, total=False):
    task: str
    candidate_actions: list[str]
    scratchpad: list[dict[str, Any]]
    next_action: dict[str, Any]
    last_tool_result: dict[str, Any]
    final_response: str
    needs_input: bool
    missing_inputs: list[str]
    question: str
    # The AgentOps trace_id for this run, set by run() so callers (the CLI,
    # the eval harness, the HTTP agent-service) can link back to the trace
    # in the dashboard without scraping stdout.
    trace_id: str
    step_count: int
    max_steps: int
    failed: bool
    error_type: str
    error_message: str
    failure_stage: str
    token_usage: dict[str, int]
    budget_exceeded: bool


class ProgressEvent(TypedDict, total=False):
    type: str
    step: int
    max_steps: int
    action: str
    thought: str
    args: dict[str, Any]
    ok: bool
    summary: str

SYSTEM_PROMPT = """You are a local GitHub agent. You help with repository operations by selecting one GitHub API action at a time.

Always respond with valid JSON only. No markdown fences.

JSON format:
{
  "thought": "brief reasoning",
  "action": "one action name or FINAL or NEED_INPUT",
  "args": { ... },
  "final_response": "required when action is FINAL",
  "missing_inputs": ["field_name"],
  "question": "required when action is NEED_INPUT"
}

Rules:
- Prefer small, reversible API actions.
- Use only the candidate actions supplied for this request.
- Use the action names exactly as listed. Do not invent synonyms like "get_user_repos" when the listed action is "list_user_repos".
- If enough information has been gathered, return action FINAL.
- If the task is missing required arguments for the next action, return action NEED_INPUT instead of guessing.
- If a previous tool call failed, adapt and try a better next step.
- Keep thoughts concise.
- For requests like "my repos", "my repositories", or "repos of mine", prefer owned repositories by using affiliation "owner" unless the user asks for all accessible repositories.
- Do not claim partial or truncated data is complete. If the tool result is truncated or incomplete, ask for another API call with narrower parameters before answering.
- Before choosing an action, check whether you have every required argument. If not, ask for the smallest missing set.
"""


def _json_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(item.get("text", ""))
        return "\n".join(chunks)
    return str(content)


def _parse_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        parts = [part.strip() for part in raw.split("```") if part.strip()]
        raw = parts[-1]
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _trim_result(action: str, result: Any, limit: int = 6000) -> Any:
    if action in {"list_user_repos", "search_repositories"}:
        items = result.get("items", []) if isinstance(result, dict) else result
        if not isinstance(items, list):
            items = []
        compact_repos = []
        for repo in items[:20]:
            if not isinstance(repo, dict):
                continue
            compact_repos.append(
                {
                    "name": repo.get("name"),
                    "full_name": repo.get("full_name"),
                    "owner": (repo.get("owner") or {}).get("login"),
                    "html_url": repo.get("html_url"),
                    "description": repo.get("description"),
                    "language": repo.get("language"),
                    "private": repo.get("private"),
                    "visibility": repo.get("visibility"),
                    "stargazers_count": repo.get("stargazers_count"),
                    "forks_count": repo.get("forks_count"),
                    "updated_at": repo.get("updated_at"),
                }
            )
        if isinstance(result, dict):
            return {"total_count": result.get("total_count"), "incomplete_results": result.get("incomplete_results"), "items": compact_repos}
        return compact_repos

    if action in {"list_issues", "search_issues"}:
        items = result.get("items", []) if isinstance(result, dict) else result
        if not isinstance(items, list):
            items = []
        compact_issues = []
        for issue in items[:20]:
            if not isinstance(issue, dict):
                continue
            compact_issues.append(
                {
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "state": issue.get("state"),
                    "html_url": issue.get("html_url"),
                    "user": (issue.get("user") or {}).get("login"),
                    "labels": [label.get("name") for label in issue.get("labels", []) if isinstance(label, dict)],
                    "pull_request": bool(issue.get("pull_request")),
                    "updated_at": issue.get("updated_at"),
                }
            )
        if isinstance(result, dict):
            return {"total_count": result.get("total_count"), "incomplete_results": result.get("incomplete_results"), "items": compact_issues}
        return compact_issues

    if action in {"list_pull_requests"} and isinstance(result, list):
        compact_prs = []
        for pull in result[:20]:
            if not isinstance(pull, dict):
                continue
            compact_prs.append(
                {
                    "number": pull.get("number"),
                    "title": pull.get("title"),
                    "state": pull.get("state"),
                    "html_url": pull.get("html_url"),
                    "user": (pull.get("user") or {}).get("login"),
                    "head": (pull.get("head") or {}).get("ref"),
                    "base": (pull.get("base") or {}).get("ref"),
                    "updated_at": pull.get("updated_at"),
                }
            )
        return compact_prs

    if action in {"search_commits"} and isinstance(result, dict):
        compact_commits = []
        for item in result.get("items", [])[:20]:
            if not isinstance(item, dict):
                continue
            commit = item.get("commit") or {}
            compact_commits.append(
                {
                    "sha": item.get("sha"),
                    "html_url": item.get("html_url"),
                    "message": commit.get("message"),
                    "author": (commit.get("author") or {}).get("name"),
                    "date": (commit.get("author") or {}).get("date"),
                    "repository": (item.get("repository") or {}).get("full_name"),
                }
            )
        return {"total_count": result.get("total_count"), "incomplete_results": result.get("incomplete_results"), "items": compact_commits}

    if action in {"search_users"} and isinstance(result, dict):
        compact_users = []
        for item in result.get("items", [])[:20]:
            if not isinstance(item, dict):
                continue
            compact_users.append(
                {
                    "login": item.get("login"),
                    "type": item.get("type"),
                    "html_url": item.get("html_url"),
                    "score": item.get("score"),
                }
            )
        return {"total_count": result.get("total_count"), "incomplete_results": result.get("incomplete_results"), "items": compact_users}

    if action in {"get_pull_request_diff", "get_pull_request_patch"} and isinstance(result, dict):
        content = result.get("content", "")
        if isinstance(content, str) and len(content) > limit:
            return {"media_type": result.get("media_type"), "truncated": True, "preview": content[:limit]}

    text = json.dumps(result, ensure_ascii=True, default=str)
    if len(text) <= limit:
        return result
    return {"truncated": True, "preview": text[:limit]}


class GitHubAgent:
    def __init__(
        self,
        model_base_url: str,
        model_name: str,
        api_key: str,
        http_referer: str,
        app_name: str,
        github_client: GitHubClient,
        max_steps: int = 6,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        self.max_steps = max_steps
        self.github_client = github_client
        self.progress_callback = progress_callback
        self.retriever = ActionRetriever(ACTION_REGISTRY)

        # --- Tier 1 configuration (env-driven, all optional) -------
        # Cost-aware self-termination: stop the agent once cumulative
        # LLM token usage reaches this budget. 0 = unlimited.
        self.max_total_tokens = int(
            os.getenv("AGENT_MAX_TOTAL_TOKENS", "0")
        )
        # Destructive-action guardrail policy:
        #   deny    -> block every destructive action
        #   confirm -> prompt stdin for y/N approval (default)
        #   allow   -> execute without gating
        self.destructive_policy = os.getenv(
            "AGENT_DESTRUCTIVE_ACTION_POLICY", "confirm"
        ).lower()
        # LLM-judge decision-quality eval: runs an extra LLM call at
        # the end of each run to score the planner's decisions.
        self.judge_enabled = (
            os.getenv("AGENT_DECISION_JUDGE", "0") == "1"
        )
        self.llm = ChatOpenAI(
            model=model_name,
            base_url=model_base_url,
            api_key=api_key,
            temperature=0,
            default_headers={
                "HTTP-Referer": http_referer,
                "X-Title": app_name,
            },
        )
        self.ops = AgentOps(
            emitters=[
                ConsoleEmitter(),
                HTTPEmitter(
                    # Configurable so the agent can emit to the ingestion
                    # API over the compose network in a hosted deployment
                    # (AGENTOPS_ENDPOINT=http://ingestion-api:8000/events).
                    # Defaults to the local dev address.
                    endpoint=os.getenv(
                        "AGENTOPS_ENDPOINT",
                        "http://127.0.0.1:8000/events",
                    ),
                ),
            ]
        )
        self.graph = self._build_graph()

    def _progress(self, event: ProgressEvent) -> None:
        if self.progress_callback:
            self.progress_callback(event)

    def _normalize_action_name(self, action: str) -> str:
        aliases = {
            "get_user_repos": "list_user_repos",
            "get_repos": "list_user_repos",
            "get_repo_contents": "get_contents",
            "get_pull_request_files": "list_pull_request_files",
            "list_prs": "list_pull_requests",
            "get_pr": "get_pull_request",
            "merge_pr": "merge_pull_request",
            "update_pr": "update_pull_request",
            "request_reviewers": "request_pull_request_reviewers",
            "inline_review_comment": "create_pull_request_review_comment",
            "close_issue": "set_issue_state",
            "reopen_issue": "set_issue_state",
            "get_actions_runs": "list_actions_runs",
            "get_check_runs": "get_check_runs",
        }
        return aliases.get(action, action)

    # Action prefixes that mutate GitHub state. Anything starting
    # with these is treated as destructive and routed through the
    # guardrail. Read-only actions (get_/list_/search_) are never
    # gated. Unknown actions default to destructive (safe default).
    DESTRUCTIVE_PREFIXES = (
        "create_",
        "update_",
        "merge_",
        "add_",
        "delete_",
        "edit_",
        "set_",
        "remove_",
        "put_",  # put_contents: create-or-update a single file (a real commit)
    )

    def _is_destructive(self, action: str) -> bool:
        return action.startswith(
            self.DESTRUCTIVE_PREFIXES
        ) or action in {"fork", "push", "commit"}

    def _check_guardrail(
        self, action: str, args: dict[str, Any]
    ) -> tuple[bool, str]:
        """
        Apply the destructive-action policy. Returns (allowed, reason).

        deny    -> always block.
        confirm -> prompt the user on stdin; block unless approved.
        allow   -> always permit.
        """
        policy = self.destructive_policy
        if policy == "allow":
            return True, "allowed (policy=allow)"
        if policy == "deny":
            return False, (
                f"blocked by guardrail (policy=deny): "
                f"{action} is destructive"
            )

        # confirm
        try:
            ans = input(
                f"\n⚠❤️  Agent wants to run destructive "
                f"action '{action}' with args {args}. "
                f"Approve? [y/N] "
            ).strip().lower()
        except EOFError:
            ans = ""

        if ans in ("y", "yes"):
            return True, "approved by user"
        return False, (
            f"blocked by guardrail (not approved): {action}"
        )

    def _candidate_actions_for_state(self, state: AgentState) -> list[ActionDefinition]:
        retrieval_parts = [state["task"]]
        last_tool_result = state.get("last_tool_result")
        if last_tool_result:
            retrieval_parts.append(json.dumps(last_tool_result, ensure_ascii=True, default=str))
        scratchpad = state.get("scratchpad", [])
        if scratchpad:
            retrieval_parts.extend(
                step.get("action", "")
                for step in scratchpad[-3:]
                if isinstance(step, dict) and step.get("action")
            )
        retrieval_query = "\n".join(part for part in retrieval_parts if part)
        return self.retriever.retrieve(retrieval_query, top_k=8)

    def _coerce_value(self, value: Any, expected_type: type) -> Any:
        if expected_type is int:
            if isinstance(value, bool):
                raise ValueError("expected integer, got boolean")
            return int(value)
        if expected_type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes"}:
                    return True
                if normalized in {"false", "0", "no"}:
                    return False
            raise ValueError("expected boolean")
        if expected_type is list:
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("["):
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                if stripped:
                    return [part.strip() for part in stripped.split(",") if part.strip()]
            raise ValueError("expected list")
        if expected_type is str:
            if value is None:
                raise ValueError("expected string")
            return str(value)
        return value

    def _validate_action_args(self, action: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
        definition = get_action_definition(action)
        if not definition:
            return None, [], [f"Unsupported action requested by model: {action}"]

        normalized: dict[str, Any] = {}
        missing: list[str] = []
        errors: list[str] = []

        for name, expected_type in definition.required.items():
            value = args.get(name) if name in args else None
            if action == "get_contents" and name == "path" and value == "":
                normalized[name] = "/"
                continue
            if name not in args or value in (None, ""):
                missing.append(name)
                continue
            try:
                normalized[name] = self._coerce_value(value, expected_type)
            except (TypeError, ValueError) as exc:
                errors.append(f"{name}: {exc}")

        for name, expected_type in definition.optional.items():
            if name not in args or args[name] is None:
                continue
            try:
                normalized[name] = self._coerce_value(args[name], expected_type)
            except (TypeError, ValueError) as exc:
                errors.append(f"{name}: {exc}")

        allowed = set(definition.required) | set(definition.optional)
        extras = sorted(key for key in args if key not in allowed)
        if extras:
            errors.append(f"unexpected arguments: {', '.join(extras)}")

        if missing or errors:
            return None, missing, errors
        return normalized, [], []

    def _summarize_result(self, action: str, result: Any) -> str:
        if action == "list_user_repos" and isinstance(result, list):
            preview = ", ".join(
                repo.get("full_name", "?")
                for repo in result[:3]
                if isinstance(repo, dict) and repo.get("full_name")
            )
            if preview:
                return f"Fetched {len(result)} repositories. Preview: {preview}"
            return f"Fetched {len(result)} repositories."
        if action == "get_user" and isinstance(result, dict):
            login = result.get("login")
            return f"Authenticated as {login}." if login else "Fetched authenticated user."
        if action == "list_branches" and isinstance(result, list):
            return f"Fetched {len(result)} branches."
        if action == "list_issues" and isinstance(result, list):
            return f"Fetched {len(result)} issues."
        if action == "list_pull_requests" and isinstance(result, list):
            return f"Fetched {len(result)} pull requests."
        if action == "list_pull_request_files" and isinstance(result, list):
            return f"Fetched {len(result)} changed files."
        if action in {"search_repositories", "search_issues", "search_commits", "search_users"} and isinstance(result, dict):
            total = result.get("total_count")
            items = result.get("items", [])
            if total is not None:
                return f"Search returned {total} total matches; fetched {len(items)}."
            return f"Fetched {len(items)} search results."
        if action in {"get_pull_request_diff", "get_pull_request_patch"} and isinstance(result, dict):
            content = result.get("content", "")
            if isinstance(content, str):
                return f"Fetched {len(content)} characters of PR {result.get('media_type')} content."
        if action == "create_multi_file_commit" and isinstance(result, dict):
            commit = result.get("commit") or {}
            return f"Committed {result.get('files_changed')} files to {result.get('branch')} at {commit.get('sha')}."
        if action == "list_actions_runs" and isinstance(result, dict):
            runs = result.get("workflow_runs", [])
            return f"Fetched {len(runs)} workflow runs."
        if action == "get_rate_limit" and isinstance(result, dict):
            core = result.get("resources", {}).get("core", {})
            remaining = core.get("remaining")
            limit = core.get("limit")
            if remaining is not None and limit is not None:
                return f"Core rate limit: {remaining}/{limit} remaining."
        if isinstance(result, dict):
            keys = ", ".join(list(result.keys())[:5])
            return f"Received object with keys: {keys}."
        if isinstance(result, list):
            return f"Received list with {len(result)} items."
        return "Received response from GitHub."

    def _invoke_planner(self, messages: list[Any]) -> AIMessage:
        attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                with self.ops.llm(
                    name=self.llm.model_name,
                    provider="OpenRouter",
                    model=self.llm.model_name,
                ) as llm_span:

                    # Record the prompts being sent to the model so a
                    # trace shows what produced a decision, not just that
                    # a decision was made.
                    system_text = None
                    user_text = None
                    if messages and isinstance(messages[0], SystemMessage):
                        system_text = messages[0].content
                    elif messages:
                        user_text = messages[0].content
                    if len(messages) > 1:
                        user_text = messages[1].content
                    llm_span.set_prompts(
                        system=system_text,
                        user=user_text,
                    )
                    llm_span.set_params(temperature=0)

                    response = self.llm.invoke(messages)

                    usage = getattr(response, "usage_metadata", None) or {}

                    llm_span.set_usage(
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                    )

                    metadata = getattr(
                        response,
                        "response_metadata",
                        None,
                    ) or {}

                    token_usage = metadata.get("token_usage", {}) or {}

                    llm_span.set_response_metadata(
                        actual_model=metadata.get("model_name"),
                        cost_usd=token_usage.get("cost"),
                        finish_reason=metadata.get("finish_reason"),
                    )
                    llm_span.set_completion(
                        text=getattr(response, "content", None),
                        finish_reason=metadata.get("finish_reason"),
                    )

                    return response

            except Exception as exc:
                last_error = exc

                if attempt == attempts:
                    break

                self._progress(
                    {
                        "type": "planning_retry",
                        "summary": (
                            f"Planner call failed ({exc}). "
                            f"Retrying {attempt}/{attempts - 1}..."
                        ),
                    }
                )

                time.sleep(1.5 * attempt)

        assert last_error is not None
        raise last_error

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("plan", self._plan_step)
        graph.add_node("act", self._act_step)
        graph.add_node("finish", self._finish_step)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "act": "act",
                "finish": "finish",
            },
        )
        graph.add_edge("act", "plan")
        graph.add_edge("finish", END)
        return graph.compile()

    def _plan_step(self, state: AgentState) -> AgentState:
        planner_failed = False
        planner_error_type = None
        planner_error_message = None
        next_step = state.get("step_count", 0) + 1
        self._progress({"type": "planning_started", "step": next_step, "max_steps": state.get("max_steps", self.max_steps)})
        scratchpad = state.get("scratchpad", [])
        candidates = self._candidate_actions_for_state(state)
        candidate_names = [candidate.name for candidate in candidates]
        self._progress(
            {
                "type": "candidate_actions",
                "step": next_step,
                "max_steps": state.get("max_steps", self.max_steps),
                "summary": ", ".join(candidate_names),
            }
        )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "task": state["task"],
                        "candidate_actions": candidate_names,
                        "candidate_details": format_candidates_for_prompt(candidates),
                        "step_count": state.get("step_count", 0),
                        "max_steps": state.get("max_steps", self.max_steps),
                        "history": scratchpad[-6:],
                        "last_tool_result": state.get("last_tool_result"),
                    },
                    ensure_ascii=True,
                )
            ),
        ]
        planner_failed = False

        # Tokens consumed by this planner call. Captured from the
        # LangChain response's usage_metadata; stays {} if the call
        # failed before returning.
        plan_usage: dict[str, Any] = {}

        with self.ops.planner(model=self.llm.model_name) as planner_span:
            try:
                response = self._invoke_planner(messages)
                payload = _parse_json(_json_text(response))
                plan_usage = (
                    getattr(response, "usage_metadata", None) or {}
                )

            except Exception as exc:
                planner_failed = True
                planner_error_type = type(exc).__name__
                planner_error_message = str(exc)

                self._progress(
                    {
                        "type": "planning_failed",
                        "step": next_step,
                        "max_steps": state.get(
                            "max_steps",
                            self.max_steps,
                        ),
                        "summary": str(exc),
                    }
                )

                payload = {
                    "action": "FINAL",
                    "final_response": (
                        "The model provider failed while planning the next step. "
                        "This is usually temporary. Please retry the command."
                    ),
                    "thought": "Planner failed due to provider error.",
                    "args": {},
                }
                planner_span.set_error(error_message=str(exc))

            # --- Cost-aware self-termination (Tier 1 #1) ----------
            # Accumulate this step's token usage against the budget.
            # If the budget is exceeded, override the decision to FINAL
            # so the agent stops instead of spending more.
            prev_usage = state.get("token_usage") or {
                "input": 0,
                "output": 0,
                "total": 0,
            }
            step_in = plan_usage.get("input_tokens") or 0
            step_out = plan_usage.get("output_tokens") or 0
            used_total = prev_usage["total"] + step_in + step_out
            new_usage = {
                "input": prev_usage["input"] + step_in,
                "output": prev_usage["output"] + step_out,
                "total": used_total,
            }
            budget_exceeded = False
            if (
                self.max_total_tokens
                and used_total >= self.max_total_tokens
            ):
                budget_exceeded = True
                payload = {
                    "action": "FINAL",
                    "final_response": (
                        f"Agent stopped to control cost: token "
                        f"budget exceeded (used {used_total} / "
                        f"budget {self.max_total_tokens} tokens)."
                    ),
                    "thought": (
                        f"Budget exceeded (used {used_total}/"
                        f"{self.max_total_tokens}); terminating."
                    ),
                    "args": {},
                }
                self._progress(
                    {
                        "type": "budget_exceeded",
                        "step": next_step,
                        "used_tokens": used_total,
                        "budget_tokens": self.max_total_tokens,
                    }
                )

            # Attach the planner's reasoning to the span: the candidates
            # it was offered, the action it chose, the ones it rejected,
            # and its stated thought. This makes the decision queryable.
            chosen = payload.get("action")
            planner_span.set_plan(
                thought=payload.get("thought"),
                candidates=candidate_names,
                chosen_action=chosen,
                rejected_actions=(
                    [c for c in candidate_names if c != chosen]
                    if chosen and chosen not in {"FINAL", "NEED_INPUT"}
                    else candidate_names
                ),
                confidence=payload.get("confidence"),
                iteration=next_step,
            )
            # Persist the cost/budget telemetry and any final response
            # onto the planner span payload (via the SDK extra-merge path)
            # so a budget termination and the running token tally are
            # queryable on the decision, not just held in agent state.
            planner_span.set_params(
                budget_exceeded=budget_exceeded,
                token_usage=new_usage,
            )
            if payload.get("final_response"):
                planner_span.set_params(
                    final_response=payload.get("final_response"),
                )
        self._progress(
            {
                "type": "planning_finished",
                "step": next_step,
                "max_steps": state.get("max_steps", self.max_steps),
                "action": payload.get("action", ""),
                "thought": payload.get("thought", ""),
                "args": payload.get("args", {}),
            }
        )
        result = {
                "candidate_actions": candidate_names,
                "next_action": payload,
                "step_count": state.get("step_count", 0),
                "failed": (
                    state.get("failed", False)
                    or planner_failed
                ),
                "token_usage": new_usage,
                "budget_exceeded": budget_exceeded,
            }

        if planner_failed:  
            result.update(
            {
                "error_type": planner_error_type,
                "error_message": planner_error_message,
                "failure_stage": "planner",
            }
        )

        return result

    def _route_after_plan(self, state: AgentState) -> Literal["act", "finish"]:
        action = state["next_action"]["action"]
        if action in {"FINAL", "NEED_INPUT"} or state.get("step_count", 0) >= state.get("max_steps", self.max_steps):
            return "finish"
        return "act"

    def _act_step(self, state: AgentState) -> AgentState:
        raw_action = state["next_action"]["action"]
        action = self._normalize_action_name(raw_action)
        args = state["next_action"].get("args", {})
        step = state.get("step_count", 0) + 1
        allowed_actions = set(state.get("candidate_actions", []))
        if allowed_actions and action not in allowed_actions:
            summary = f"action {action} was not in the retrieved candidate set: {', '.join(sorted(allowed_actions))}"
            self._progress(
                {
                    "type": "action_finished",
                    "step": step,
                    "max_steps": state.get("max_steps", self.max_steps),
                    "action": action,
                    "args": args,
                    "ok": False,
                    "summary": summary,
                }
            )
            scratchpad = list(state.get("scratchpad", []))
            scratchpad.append(
                {
                    "thought": state["next_action"].get("thought", ""),
                    "action": action,
                    "raw_action": raw_action,
                    "args": args,
                    "tool_result": {"ok": False, "action": action, "args": args, "errors": [summary]},
                }
            )
            return {
                "scratchpad": scratchpad,
                "last_tool_result": {"ok": False, "action": action, "args": args, "errors": [summary]},
                "step_count": state.get("step_count", 0) + 1,
            }
        validated_args, missing, errors = self._validate_action_args(action, args)
        if missing or errors:
            summary_parts: list[str] = []
            if missing:
                summary_parts.append(f"missing inputs: {', '.join(missing)}")
            if errors:
                summary_parts.append(f"validation errors: {'; '.join(errors)}")
            self._progress(
                {
                    "type": "action_finished",
                    "step": step,
                    "max_steps": state.get("max_steps", self.max_steps),
                    "action": action,
                    "args": args,
                    "ok": False,
                    "summary": ". ".join(summary_parts),
                }
            )
            scratchpad = list(state.get("scratchpad", []))
            scratchpad.append(
                {
                    "thought": state["next_action"].get("thought", ""),
                    "action": action,
                    "raw_action": raw_action,
                    "args": args,
                    "tool_result": {
                        "ok": False,
                        "action": action,
                        "args": args,
                        "missing": missing,
                        "errors": errors,
                    },
                }
            )
            return {
                "scratchpad": scratchpad,
                "last_tool_result": {
                    "ok": False,
                    "action": action,
                    "args": args,
                    "missing": missing,
                    "errors": errors,
                },
                "step_count": state.get("step_count", 0) + 1,
            }
        self._progress(
            {
                "type": "action_started",
                "step": step,
                "max_steps": state.get("max_steps", self.max_steps),
                "action": action,
                "args": validated_args,
            }
        )
        # --- Destructive-action guardrail (Tier 1 #2) ----------
        # Gate mutating actions behind the configured policy. A blocked
        # action is recorded as an errored tool span (so it shows up in
        # the execution tree) and returned to the scratchpad as a
        # failed tool_result so the planner can re-plan around it.
        if self._is_destructive(action):
            allowed, reason = self._check_guardrail(
                action, validated_args
            )
            if not allowed:
                self._progress(
                    {
                        "type": "action_blocked",
                        "step": step,
                        "max_steps": state.get(
                            "max_steps", self.max_steps
                        ),
                        "action": action,
                        "args": validated_args,
                        "policy": self.destructive_policy,
                        "summary": reason,
                    }
                )
                with self.ops.tool(
                    name=action, args=validated_args
                ) as tool_span:
                    tool_span.set_error(error_message=reason)

                block_result = {
                    "ok": False,
                    "action": action,
                    "args": validated_args,
                    "error": reason,
                }
                scratchpad = list(state.get("scratchpad", []))
                scratchpad.append(
                    {
                        "thought": state["next_action"].get(
                            "thought", ""
                        ),
                        "action": action,
                        "raw_action": raw_action,
                        "args": validated_args,
                        "tool_result": block_result,
                    }
                )
                return {
                    "scratchpad": scratchpad,
                    "last_tool_result": block_result,
                    "step_count": state.get("step_count", 0) + 1,
                }

        scratchpad = list(state.get("scratchpad", []))
        try:
            method = getattr(self.github_client, action)
        except AttributeError as exc:
            raise ValueError(f"Unsupported action requested by model: {action}") from exc

        try:
            with self.ops.tool(name=action, args=validated_args) as tool_span:
                result = method(**validated_args)
                tool_span.set_result(
                    return_value=_trim_result(action, result),
                    http_status=self.github_client.last_status,
                    result_size=self.github_client.last_size_bytes,
                )
            tool_result = {"ok": True, "action": action, "args": validated_args, "result": _trim_result(action, result)}
            self._progress(
                {
                    "type": "action_finished",
                    "step": step,
                    "max_steps": state.get("max_steps", self.max_steps),
                    "action": action,
                    "args": validated_args,
                    "ok": True,
                    "summary": self._summarize_result(action, result),
                }
            )
        except GitHubAPIError as exc:
            tool_span.set_error(error_message=str(exc))
            tool_result = {"ok": False, "action": action, "args": validated_args, "error": str(exc)}
            self._progress(
                {
                    "type": "action_finished",
                    "step": step,
                    "max_steps": state.get("max_steps", self.max_steps),
                    "action": action,
                    "args": validated_args,
                    "ok": False,
                    "summary": str(exc),
                }
            )

        scratchpad.append(
            {
                "thought": state["next_action"].get("thought", ""),
                "action": action,
                "raw_action": raw_action,
                "args": validated_args,
                "tool_result": tool_result,
            }
        )
        return {
            "scratchpad": scratchpad,
            "last_tool_result": tool_result,
            "step_count": state.get("step_count", 0) + 1,
        }

    def _finish_step(self, state: AgentState) -> AgentState:
        self._progress(
            {
                "type": "finalizing",
                "step": state.get("step_count", 0),
                "max_steps": state.get("max_steps", self.max_steps),
            }
        )
        planned = state.get("next_action", {})
        if planned.get("action") == "NEED_INPUT":
            missing_inputs = planned.get("missing_inputs") or []
            question = planned.get("question") or "I need more information before I can continue."
            suffix = f" Missing inputs: {', '.join(missing_inputs)}." if missing_inputs else ""
            return {
                "final_response": f"{question}{suffix}",
                "needs_input": True,
                "missing_inputs": missing_inputs,
                "question": question,
            }
        final_response = planned.get("final_response")
        if not final_response:
            if state.get("step_count", 0) >= state.get("max_steps", self.max_steps):
                final_response = "Stopped because the maximum number of agent steps was reached. Review the scratchpad for details."
            else:
                final_response = "No final response was produced."
        return {"final_response": final_response, "needs_input": False}

    def _evaluate_decisions(
        self, task: str, result: AgentState
    ) -> dict[str, Any] | None:
        """
        LLM-judge decision-quality evaluation (Tier 1 #3).

        After a run completes, send the planner's decision transcript
        to the LLM and ask it to score the decision-making quality.
        The score, summary, strengths and weaknesses are attached to
        a dedicated ``decision-quality-judge`` LLM span (a child of
        the trace) via the span's free-form ``extra`` payload, so the
        dashboard can surface a "Decision Quality" panel per run.
        """
        scratchpad = result.get("scratchpad", []) or []
        if not scratchpad:
            return None

        transcript_lines: list[str] = []
        for i, step in enumerate(scratchpad, 1):
            thought = step.get("thought", "")
            action = step.get("action", "")
            tool_result = step.get("tool_result", {}) or {}
            if tool_result.get("ok"):
                outcome = tool_result.get("summary") or "ok"
            else:
                outcome = (
                    tool_result.get("error")
                    or tool_result.get("summary")
                    or "failed"
                )
            transcript_lines.append(
                f"Step {i}: thought={thought!r} "
                f"action={action} outcome={outcome}"
            )
        transcript = "\n".join(transcript_lines)

        system = (
            "You are a strict evaluator scoring an AI agent's "
            "decision-making. Given the user's task and the agent's "
            "sequence of planner decisions (each with the agent's "
            "stated thought, the action it chose, and the outcome), "
            "rate the quality of the agent's decisions on relevance, "
            "efficiency, and correctness. Respond with valid JSON "
            "only, no markdown fences:\n"
            '{"score": <integer 1-5>, '
            '"summary": "<one sentence>", '
            '"strengths": ["...", "..."], '
            '"weaknesses": ["...", "..."]}'
        )
        user = (
            f"Task: {task}\n\nDecisions:\n{transcript}\n\n"
            f"Return the JSON evaluation."
        )

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]

        with self.ops.llm(
            name="decision-quality-judge",
            provider="OpenRouter",
            model=self.llm.model_name,
        ) as judge_span:
            judge_span.set_prompts(system=system, user=user)
            judge_span.set_params(temperature=0)

            response = self.llm.invoke(messages)

            usage = (
                getattr(response, "usage_metadata", None) or {}
            )
            judge_span.set_usage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )
            judge_span.set_completion(
                text=getattr(response, "content", None)
            )

            parsed = _parse_json(_json_text(response)) or {}

            # Attach the eval result to the span payload via the
            # free-form extra dict (merged into the payload by
            # LLMSpan.to_payload).
            judge_span.set_params(
                eval_score=parsed.get("score"),
                eval_summary=parsed.get("summary"),
                eval_strengths=parsed.get("strengths"),
                eval_weaknesses=parsed.get("weaknesses"),
            )

            return parsed

    def run(self, task: str, user_query: str | None = None) -> AgentState:
        initial_state: AgentState = {
            "task": task,
            "scratchpad": [],
            "step_count": 0,
            "max_steps": self.max_steps,
            "failed": False,
        }

        with self.ops.trace(
            "github-agent",
            payload={
                "task": task,
                # The user's original ask, before conversation-memory /
                # clarification context is prepended. Surfaced in the
                # dashboard trace view so a reader can see what was asked.
                "user_query": user_query or task,
                "session_id": str(uuid.uuid4()),
                "agent_name": "github-agent",
                "agent_version": "0.1.0",
                "framework": "langgraph",
                "budget_tokens": self.max_total_tokens,
                "destructive_policy": self.destructive_policy,
            },
        ) as trace:
            # The trace span is top-of-stack here; capture its id before
            # invoke so it survives even if child spans leave the stack in
            # an unexpected state. Surfaced to callers via result.
            _trace_id = self.ops.context.current().trace_id

            result = self.graph.invoke(initial_state)

            if result.get("failed", False):
                trace.set_error(
                    error_type=result.get(
                        "error_type",
                        "AgentExecutionError",
                    ),
                    error_message=result.get(
                        "error_message",
                        "Agent execution failed",
                    ),
                    failure_stage=result.get(
                        "failure_stage",
                        "agent",
                    ),
                )

            # LLM-judge decision-quality eval (Tier 1 #3). Runs an
            # extra LLM call over the run's decisions and records the
            # score/critique as a child span of this trace.
            if self.judge_enabled:
                try:
                    self._evaluate_decisions(task, result)
                except Exception as exc:
                    self._progress(
                        {
                            "type": "judge_failed",
                            "summary": str(exc),
                        }
                    )

            result["trace_id"] = _trace_id
        return result
