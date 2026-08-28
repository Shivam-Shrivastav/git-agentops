#!/usr/bin/env python3
"""Run the 20 github-agent eval cases and capture structured results.

For each case in cases.tsv we invoke the installed github-agent CLI with
the case's env flags, capture stdout, retry on transient free-model
failures (empty/non-JSON provider responses), and parse out the
trace_id, final status, chosen actions, budget_exceeded / action_blocked
signals, and judge-span presence. Results are written to runs.json; raw
stdout is kept in logs/run_NN.log for the report builder.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GH = ROOT.parent / "github-agent"
AGENT = GH / ".venv" / "bin" / "github-agent"
# cases file (argv[1]), runs.json (argv[2] or derived), logs dir (argv[3] or derived)
CASES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cases.tsv"
RUNS_JSON = Path(sys.argv[2]) if len(sys.argv) > 2 else CASES.parent / f"{CASES.stem}_runs.json"
LOG_DIR = Path(sys.argv[3]) if len(sys.argv) > 3 else CASES.parent / f"{CASES.stem}_logs"

MAX_ATTEMPTS = 3
RUN_TIMEOUT = 300  # seconds per attempt (NEED_INPUT cases run 2+ rounds)

TRACE_RE = re.compile(r'"trace_id":\s*"([0-9a-f-]+)"')
END_RE = re.compile(r"agent\.end\s+github-agent\s+status=(\w+)\s+duration=([\d.]+)")
CHOSE_RE = re.compile(r"Model chose action:\s*(\S+)")
BUDGET_RE = re.compile(r'"type":\s*"budget_exceeded"')
BLOCK_RE = re.compile(r'"type":\s*"action_blocked".*?"action":\s*"([^"]+)"', re.DOTALL)
JUDGE_RE = re.compile(r"decision-quality-judge")
FAIL_RE = re.compile(r"JSONDecodeError|model provider failed|Expecting value", re.I)
NEEDS_INPUT_RE = re.compile(r"Agent needs more information", re.I)


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env["AGENTOPS_API_KEY"] = env.get("AGENTOPS_API_KEY", "dev")
    env["AGENTOPS_ENDPOINT"] = env.get("AGENTOPS_ENDPOINT", "http://127.0.0.1:8000/events")
    # Pull secrets from the agent .env without printing them.
    envfile = GH / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip("'\""))
    return env


def load_cases() -> list[dict]:
    cases = []
    lines = CASES.read_text().splitlines()
    header = lines[0].split("\t")
    for line in lines[1:]:
        if not line.strip():
            continue
        cases.append(dict(zip(header, line.split("\t"))))
    return cases


def run_once(case: dict, env: dict[str, str]) -> tuple[str, int]:
    case_env = dict(env)
    for flag in case["flags"].split():
        if "=" in flag:
            k, v = flag.split("=", 1)
            case_env[k] = v
    stdin = case.get("stdin") or ""
    try:
        proc = subprocess.run(
            [str(AGENT), case["query"]],
            cwd=str(GH),
            env=case_env,
            input=stdin.encode() if stdin else None,
            capture_output=True,
            timeout=RUN_TIMEOUT,
        )
        out = proc.stdout.decode("utf-8", "replace")
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        out = "[TIMEOUT]"
        rc = -1
    return out, rc


def parse(out: str) -> dict:
    # NEED_INPUT cases go through >=2 agent.run() calls, each emitting its
    # own trace_id and agent.end event. The LAST one is the run that
    # actually executed the action after clarification, so take the final
    # match, not the first.
    trace_ids = TRACE_RE.findall(out)
    end_matches = END_RE.findall(out)
    trace_id = trace_ids[-1] if trace_ids else None
    if end_matches:
        status = end_matches[-1][0]
        duration_ms = float(end_matches[-1][1])
    elif "[TIMEOUT]" in out:
        status, duration_ms = "timeout", None
    else:
        status, duration_ms = "unknown", None
    return {
        "trace_id": trace_id,
        "status": status,
        "duration_ms": duration_ms,
        "chosen_actions": CHOSE_RE.findall(out),
        "budget_exceeded": bool(BUDGET_RE.search(out)),
        "blocked_actions": BLOCK_RE.findall(out),
        "guardrail_blocked": bool(BLOCK_RE.search(out)),
        "judge_ran": bool(JUDGE_RE.search(out)),
        "transient_fail": bool(FAIL_RE.search(out)),
        "asked_input": bool(NEEDS_INPUT_RE.search(out)),
    }


def main() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    env = load_env()
    cases = load_cases()
    results = []
    for case in cases:
        n = case["n"]
        parsed = None
        attempts = 0
        last_out = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts = attempt
            out, rc = run_once(case, env)
            last_out = out
            parsed = parse(out)
            # Retry only on transient provider failures, and only when a
            # successful run is what the case expects.
            expect_ok = case["expect_status"] in ("success", "any")
            if parsed["transient_fail"] and expect_ok and attempt < MAX_ATTEMPTS:
                continue
            break
        (LOG_DIR / f"run_{n}.log").write_text(last_out)
        record = {**case, **parsed, "attempts": attempts, "log": f"logs/run_{n}.log"}
        results.append(record)
        status = parsed["status"]
        acts = ",".join(parsed["chosen_actions"]) or "-"
        blk = ",".join(parsed["blocked_actions"]) or "-"
        print(
            f"[{n}] cat={case['category']:<14} status={status:<8} "
            f"attempts={attempts} actions={acts} blocked={blk} "
            f"budget={parsed['budget_exceeded']} judge={parsed['judge_ran']} "
            f"asked_input={parsed['asked_input']} "
            f"trace={parsed['trace_id']}",
            flush=True,
        )
    RUNS_JSON.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {RUNS_JSON} ({len(results)} cases)")


if __name__ == "__main__":
    sys.exit(main())