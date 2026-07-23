from __future__ import annotations

import json
import time
from typing import Any, Callable, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from github_agent.github_api import GitHubAPIError, GitHubClient
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
    step_count: int
    max_steps: int


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
                return self.llm.invoke(messages)
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    break
                self._progress(
                    {
                        "type": "planning_retry",
                        "summary": f"Planner call failed ({exc}). Retrying {attempt}/{attempts - 1}...",
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
        try:
            response = self._invoke_planner(messages)
            payload = _parse_json(_json_text(response))
        except Exception as exc:
            self._progress(
                {
                    "type": "planning_failed",
                    "step": next_step,
                    "max_steps": state.get("max_steps", self.max_steps),
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
        return {
            "candidate_actions": candidate_names,
            "next_action": payload,
            "step_count": state.get("step_count", 0),
        }

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
        scratchpad = list(state.get("scratchpad", []))
        try:
            method = getattr(self.github_client, action)
        except AttributeError as exc:
            raise ValueError(f"Unsupported action requested by model: {action}") from exc

        try:
            result = method(**validated_args)
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

    def run(self, task: str) -> AgentState:
        initial_state: AgentState = {
            "task": task,
            "scratchpad": [],
            "step_count": 0,
            "max_steps": self.max_steps,
        }
        return self.graph.invoke(initial_state)
