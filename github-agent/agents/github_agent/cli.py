from __future__ import annotations

import argparse
import json
import sys
import time

from github_agent.config import Settings
from github_agent.github_api import GitHubClient
from github_agent.graph import GitHubAgent
from github_agent.memory import build_context_prefix, load_memory, save_memory, update_memory_from_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub agent using LangGraph and OpenRouter.")
    parser.add_argument("task", help="Natural-language task for the GitHub agent.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full LangGraph result as JSON instead of a human summary.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    start_time = time.time()

    def elapsed() -> str:
        return f"{time.time() - start_time:0.1f}s"

    def compact_json(value: object) -> str:
        text = json.dumps(value, ensure_ascii=True, default=str)
        if len(text) > 160:
            return text[:157] + "..."
        return text

    def progress(event: dict[str, object]) -> None:
        event_type = str(event.get("type", ""))
        step = event.get("step")
        max_steps = event.get("max_steps")
        prefix = f"[agent {elapsed()}]"
        step_label = f" [step {step}/{max_steps}]" if step and max_steps else ""

        if event_type == "planning_started":
            print(f"{prefix}{step_label} Planning next action...", file=sys.stderr, flush=True)
            return

        if event_type == "candidate_actions":
            summary = str(event.get("summary", "")).strip()
            print(f"{prefix}{step_label} Candidate actions: {summary}", file=sys.stderr, flush=True)
            return

        if event_type == "planning_retry":
            summary = str(event.get("summary", "")).strip()
            print(f"{prefix}{step_label} Planner retry: {summary}", file=sys.stderr, flush=True)
            return

        if event_type == "planning_failed":
            summary = str(event.get("summary", "")).strip()
            print(f"{prefix}{step_label} Planner failed: {summary}", file=sys.stderr, flush=True)
            return

        if event_type == "planning_finished":
            action = event.get("action", "")
            thought = str(event.get("thought", "")).strip()
            args = event.get("args", {})
            print(f"{prefix}{step_label} Model chose action: {action}", file=sys.stderr, flush=True)
            if thought:
                print(f"{prefix}{step_label} Reasoning: {thought}", file=sys.stderr, flush=True)
            if args:
                print(f"{prefix}{step_label} Args: {compact_json(args)}", file=sys.stderr, flush=True)
            return

        if event_type == "action_started":
            action = event.get("action", "")
            print(f"{prefix}{step_label} Calling GitHub API: {action}", file=sys.stderr, flush=True)
            return

        if event_type == "action_finished":
            action = event.get("action", "")
            ok = bool(event.get("ok"))
            summary = str(event.get("summary", "")).strip()
            status = "OK" if ok else "ERROR"
            print(f"{prefix}{step_label} {action} -> {status}", file=sys.stderr, flush=True)
            if summary:
                print(f"{prefix}{step_label} Summary: {summary}", file=sys.stderr, flush=True)
            return

        if event_type == "finalizing":
            print(f"{prefix}{step_label} Finalizing response...", file=sys.stderr, flush=True)
            return

        print(f"{prefix}{step_label} {compact_json(event)}", file=sys.stderr, flush=True)

    client = GitHubClient(token=settings.github_token, base_url=settings.github_api_base_url)
    agent = GitHubAgent(
        model_base_url=settings.openrouter_base_url,
        model_name=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        http_referer=settings.openrouter_http_referer,
        app_name=settings.openrouter_app_name,
        github_client=client,
        max_steps=settings.agent_max_steps,
        progress_callback=progress,
    )

    memory = load_memory()
    task_text = build_context_prefix(memory) + args.task
    clarification_history: list[str] = []
    clarification_round = 0

    while True:
        result = agent.run(task_text, user_query=args.task)
        if not result.get("needs_input"):
            break

        clarification_round += 1
        question = result.get("question") or result.get("final_response") or "I need more information."
        missing_inputs = result.get("missing_inputs", [])

        print("\nAgent needs more information.", file=sys.stderr, flush=True)
        print(question, file=sys.stderr, flush=True)
        if missing_inputs:
            print(f"Missing inputs: {', '.join(missing_inputs)}", file=sys.stderr, flush=True)

        try:
            user_reply = input("> ").strip()
        except EOFError:
            print(result.get("final_response", "Missing required input."), file=sys.stderr)
            raise SystemExit(1)

        if not user_reply:
            print("No input provided. Stopping.", file=sys.stderr)
            raise SystemExit(1)

        clarification_history.append(
            f"Clarification round {clarification_round}:\n"
            f"Agent asked: {question}\n"
            f"User answered: {user_reply}"
        )
        task_text = build_context_prefix(memory) + args.task + "\n\n" + "\n\n".join(clarification_history)

    updated_memory = update_memory_from_result(memory, result)
    if updated_memory != memory:
        save_memory(updated_memory)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True, default=str))
        return

    print(result.get("final_response", "No final response."))
    scratchpad = result.get("scratchpad", [])
    if scratchpad:
        print("\nAction trace:")
        for index, step in enumerate(scratchpad, start=1):
            status = "ok" if step["tool_result"]["ok"] else "error"
            print(f"{index}. {step['action']} [{status}]")


if __name__ == "__main__":
    main()
