"""JSON Wrangler agent.

Takes messy, pasted, or unstructured JSON-like text, validates it, and returns
a pretty-printed, formatted JSON block. If the input isn't valid JSON, the
agent asks the LLM to extract structured JSON first, then validates that.
"""
from __future__ import annotations

import json
from typing import Any

from .base import BaseAgent


class JSONWranglerAgent(BaseAgent):
    name = "json-wrangler-agent"
    display_name = "JSON Wrangler"
    description = "Validates and pretty-prints messy JSON text."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # 1. Try to parse the raw input directly.
        formatted, parse_error = await self._tool(
            "format_json", {"text": task}
        )

        if formatted is not None:
            self._planner_decision(
                thought="Raw input parsed as valid JSON; formatting and returning directly.",
                chosen_action="format_directly",
                candidates=["format_directly", "extract_with_llm", "report_failure"],
                rejected_actions=["extract_with_llm", "report_failure"],
                confidence=0.95,
                iteration=1,
            )
            return (
                "Valid JSON — formatted output:\n\n```json\n"
                f"{formatted}\n```"
            )

        # 2. If raw input is not JSON, ask the LLM to extract/structure it.
        self._planner_decision(
            thought=f"Direct JSON parse failed ({parse_error}); will try LLM extraction.",
            chosen_action="extract_with_llm",
            candidates=["extract_with_llm", "report_failure"],
            rejected_actions=["report_failure"],
            confidence=0.75,
            iteration=1,
        )
        system = (
            "You are a JSON extraction assistant. Given messy text, respond with "
            "valid JSON only and no markdown fences. Infer the most likely "
            "structure and represent it as JSON. If the text is too ambiguous, "
            "return a single object with a 'note' field explaining why."
        )
        extracted = await self._llm_chat(
            system,
            f"Extract JSON from this text:\n\n{task}",
            name="extract_json",
        )

        try:
            data = self._extract_json(extracted)
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            self._planner_decision(
                thought="LLM extraction succeeded and produced valid JSON.",
                chosen_action="return_extracted_json",
                candidates=["return_extracted_json", "report_failure"],
                rejected_actions=["report_failure"],
                confidence=0.85,
                iteration=2,
            )
            return (
                "The raw text wasn't valid JSON. I extracted structured JSON:\n\n"
                f"```json\n{pretty}\n```"
            )
        except Exception:
            self._planner_decision(
                thought="LLM extraction also failed; reporting the original parse error.",
                chosen_action="report_failure",
                candidates=["retry_extraction", "report_failure"],
                rejected_actions=["retry_extraction"],
                confidence=0.9,
                iteration=2,
            )
            return (
                "I couldn't parse the input as JSON, and automatic extraction failed.\n\n"
                f"Original parse error: {parse_error}"
            )

    def _tool_format_json(self, text: str) -> tuple[str | None, str | None]:
        """Try to parse and pretty-print the input text as JSON."""
        # Strip common wrappers people paste around JSON (fences, leading labels).
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[-1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

        try:
            data = json.loads(cleaned)
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            return pretty, None
        except Exception as exc:
            return None, str(exc)

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
