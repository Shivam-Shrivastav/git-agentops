from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MEMORY_PATH = Path(".github_agent_memory.json")


def load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {}
    try:
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_memory(memory: dict[str, Any]) -> None:
    MEMORY_PATH.write_text(json.dumps(memory, indent=2, ensure_ascii=True), encoding="utf-8")


def build_context_prefix(memory: dict[str, Any]) -> str:
    last_repo = memory.get("last_repo")
    if not isinstance(last_repo, dict):
        return ""

    owner = last_repo.get("owner")
    repo = last_repo.get("repo")
    if not owner or not repo:
        return ""

    return (
        "Conversation memory:\n"
        f"- Last referenced repository owner: {owner}\n"
        f"- Last referenced repository name: {repo}\n"
        f"- Last referenced full repository: {owner}/{repo}\n\n"
    )


def update_memory_from_result(memory: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(memory)
    scratchpad = result.get("scratchpad", [])
    if not isinstance(scratchpad, list):
        return updated

    for step in scratchpad:
        if not isinstance(step, dict):
            continue
        tool_result = step.get("tool_result", {})
        if not isinstance(tool_result, dict) or not tool_result.get("ok"):
            continue

        args = step.get("args", {})
        if isinstance(args, dict):
            owner = args.get("owner")
            repo = args.get("repo")
            if owner and repo:
                updated["last_repo"] = {"owner": owner, "repo": repo}

        result_payload = tool_result.get("result")
        if isinstance(result_payload, dict):
            full_name = result_payload.get("full_name")
            owner_obj = result_payload.get("owner")
            if isinstance(full_name, str) and "/" in full_name:
                owner, repo = full_name.split("/", 1)
                updated["last_repo"] = {"owner": owner, "repo": repo}
            elif isinstance(owner_obj, dict) and owner_obj.get("login") and result_payload.get("name"):
                updated["last_repo"] = {
                    "owner": owner_obj["login"],
                    "repo": result_payload["name"],
                }

    return updated
