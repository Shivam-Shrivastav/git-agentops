"""Diff Summarizer agent.

Takes two text blocks (for example before/after code or two versions of a doc)
and produces a unified diff, then asks the LLM to summarize the changes in
plain English.
"""
from __future__ import annotations

import difflib
import json
from typing import Any

from .base import BaseAgent


class DiffSummarizerAgent(BaseAgent):
    name = "diff-summarizer-agent"
    display_name = "Diff Summarizer"
    description = "Compares two text blocks and summarizes the changes."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # Try to split the user's message into two blocks.
        before, after, split_label = self._split_text(task)

        split_action = "detected_separator" if split_label else "fallback_split"
        self._planner_decision(
            thought=f"Split input into before/after blocks using {split_action}.",
            chosen_action=split_action,
            candidates=["detected_separator", "fallback_split"],
            rejected_actions=["fallback_split"] if split_label else ["detected_separator"],
            confidence=0.9 if split_label else 0.6,
            iteration=1,
        )

        diff = await self._tool(
            "compute_diff",
            {"before": before, "after": after, "label": split_label or "text"},
        )

        system = (
            "You are a code/document reviewer. Given a unified diff between two "
            "versions of a text, write a concise plain-English summary of the "
            "changes. Mention what was added, removed, or modified, and why it "
            "matters if obvious. Keep it short."
        )
        summary = await self._llm_chat(
            system,
            f"Original request: {task}\n\nUnified diff:\n```diff\n{diff}\n```",
            name="summarize_diff",
        )

        self._planner_decision(
            thought="Computed unified diff and asked LLM to summarize changes in plain English.",
            chosen_action="summarize_diff",
            candidates=["summarize_diff", "return_raw_diff"],
            rejected_actions=["return_raw_diff"],
            confidence=0.85,
            iteration=2,
        )

        return f"**Diff Summary**\n\n{summary}\n\n**Unified diff**\n```diff\n{diff}\n```"

    def _tool_compute_diff(
        self, before: str, after: str, label: str = "text"
    ) -> str:
        """Compute a unified diff between two text blocks."""
        before_lines = before.splitlines(keepends=True) or [""]
        after_lines = after.splitlines(keepends=True) or [""]
        # Ensure lines end with newline so difflib renders cleanly.
        before_lines = [
            line if line.endswith("\n") else line + "\n" for line in before_lines
        ]
        after_lines = [
            line if line.endswith("\n") else line + "\n" for line in after_lines
        ]
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{label}_before",
            tofile=f"{label}_after",
        )
        return "".join(diff)

    def _split_text(self, text: str) -> tuple[str, str, str | None]:
        """Split user text into before/after blocks.

        Supports common separators. Falls back to first half / second half.
        """
        text = text.strip()
        markers = [
            "\n---\n",
            "\n===\n",
            "\nBEFORE:\n",
            "\nAFTER:\n",
            "\nOLD:\n",
            "\nNEW:\n",
        ]
        for marker in markers:
            if marker in text:
                parts = text.split(marker, 1)
                label = None
                if marker.strip() in ("BEFORE:", "OLD:"):
                    label = "text"
                return parts[0].strip(), parts[1].strip(), label

        # Fallback: split roughly in half by lines.
        lines = text.splitlines()
        mid = max(1, len(lines) // 2)
        return "\n".join(lines[:mid]).strip(), "\n".join(lines[mid:]).strip(), None

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
