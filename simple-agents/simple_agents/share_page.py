"""Share This Page agent.

Takes a URL, fetches it, summarizes it, shortens the link, and generates a QR code.
"""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

import httpx
import segno

from .base import BaseAgent


class SharePageAgent(BaseAgent):
    name = "share-page-agent"
    display_name = "Share This Page"
    description = "Fetches a URL, summarizes it, shortens it, and makes a QR code."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # 1. Extract the URL.
        urls = re.findall(r"https?://[^\s\"'<>]+", task)
        url = urls[0] if urls else None

        if not url:
            extract_system = (
                "Extract the URL from the user's message. Respond with valid "
                "JSON only: {\"url\": \"...\"}. If there is no URL, use null."
            )
            raw = await self._llm_chat(extract_system, task, name="extract_url")
            try:
                parsed = self._extract_json(raw)
                url = parsed.get("url")
            except Exception:
                url = None

        if not url:
            return "I need a URL to share. Please paste one and I'll summarize, shorten, and generate a QR code for it."

        self._planner_decision(
            thought=f"Extracted URL to share: {url}.",
            chosen_action="extract_url",
            candidates=["extract_url", "ask_for_url"],
            rejected_actions=["ask_for_url"],
            confidence=0.9,
            iteration=1,
        )

        # 2. Fetch page.
        try:
            page_text = await self._tool("fetch_url", {"url": url})
        except Exception as exc:
            return f"I couldn't fetch that page: {exc}"

        # 3. Summarize.
        summary_system = (
            "Summarize the provided web page content in 2-3 concise sentences. "
            "Focus on what the page is about."
        )
        summary = await self._llm_chat(summary_system, page_text[:4000], name="summarize")

        # 4. Shorten URL.
        short_url: str | None = None
        short_error: str | None = None
        try:
            short_url = await self._tool("shorten_url", {"url": url})
        except Exception as exc:
            short_error = str(exc)

        # 5. Generate QR code. Use the short URL when available, otherwise
        # fall back to the original URL so the user still gets a scannable code.
        qr_target = short_url if short_url and not short_url.startswith("(") else url
        qr_b64: str | None = None
        try:
            qr_b64 = await self._tool("generate_qr", {"text": qr_target})
        except Exception as exc:
            qr_b64 = f"(QR generation failed: {exc})"

        fallback_used = not short_url
        self._planner_decision(
            thought="Fetched page, summarized, shortened, and generated QR. "
            + ("Used original URL for QR because shortening failed." if fallback_used else "Used short URL for QR."),
            chosen_action="use_original_for_qr" if fallback_used else "use_short_for_qr",
            candidates=["use_short_for_qr", "use_original_for_qr"],
            rejected_actions=["use_short_for_qr"] if fallback_used else ["use_original_for_qr"],
            confidence=0.9,
            iteration=2,
        )

        # 6. Compose final share card.
        qr_markdown = (
            f"![QR](data:image/png;base64,{qr_b64})"
            if isinstance(qr_b64, str) and not qr_b64.startswith("(")
            else f"{qr_b64}"
        )
        short_display = short_url if short_url else (f"unavailable ({short_error})" if short_error else "unavailable")
        return (
            f"**Summary**\n{summary}\n\n"
            f"**Original URL**\n{url}\n\n"
            f"**Short URL**\n{short_display}\n\n"
            f"**QR Code**\n{qr_markdown}"
        )

    async def _tool_fetch_url(self, url: str) -> str:
        """Fetch a page as markdown via r.jina.ai (no API key)."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://r.jina.ai/{url}",
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text[:6000]

    async def _tool_shorten_url(self, url: str) -> str:
        """Shorten a URL via TinyURL (no API key, public endpoint)."""
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://tinyurl.com/api-create.php",
                params={"url": url},
                follow_redirects=True,
            )
            resp.raise_for_status()
            short = resp.text.strip()
            if short.startswith("http"):
                return short
            raise RuntimeError(f"URL shortening failed: {short}")

    def _tool_generate_qr(self, text: str) -> str:
        """Generate a base64 PNG QR code."""
        qr = segno.make(text, error="m")
        buffer = io.BytesIO()
        qr.save(buffer, kind="png", scale=4)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _extract_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
