"""Local deep researcher agent.

Searches DuckDuckGo, fetches pages, and writes a cited markdown report.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .base import BaseAgent


try:
    from ddgs import DDGS
except Exception:  # pragma: no cover - dependency may be missing in some envs
    DDGS = None


class LocalResearcherAgent(BaseAgent):
    name = "local-researcher-agent"
    display_name = "Local Researcher"
    description = "Searches the live web and writes a cited markdown report."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # 1. Generate search queries.
        plan_system = (
            "You are a research planner. Given a topic, produce 1-3 web search "
            "queries that would help answer it. Respond with valid JSON only "
            "and no markdown fences. Example: "
            '{"queries": ["LangChain vs LangGraph comparison 2024"]}'
        )
        plan_raw = await self._llm_chat(plan_system, f"Topic: {task}", name="plan_queries")
        try:
            plan = self._extract_json(plan_raw)
        except Exception:
            plan = {"queries": [task]}

        queries = plan.get("queries", [task])[:3]

        self._planner_decision(
            thought=f"Planned {len(queries)} search queries to cover the topic: {queries}.",
            chosen_action="plan_queries",
            candidates=["plan_queries", "single_search", "ask_clarification"],
            rejected_actions=["single_search", "ask_clarification"],
            confidence=0.85,
            iteration=1,
        )

        # 2. Search DuckDuckGo for each query.
        all_results: list[dict[str, Any]] = []
        for query in queries:
            try:
                hits = await self._tool("web_search", {"query": query})
                all_results.extend(hits)
            except Exception as exc:
                all_results.append({"title": f"Search failed for '{query}'", "error": str(exc)})

        # 3. Fetch top 3 unique pages.
        fetched_pages: list[dict[str, Any]] = []
        seen_urls = set()
        for result in all_results:
            if not isinstance(result, dict) or "error" in result:
                continue
            url = result.get("href")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if len(fetched_pages) >= 3:
                break
            try:
                page = await self._tool("fetch_page", {"url": url})
                fetched_pages.append({"url": url, "title": result.get("title"), "text": page})
            except Exception as exc:
                fetched_pages.append({"url": url, "title": result.get("title"), "error": str(exc)})

        fetched_titles = [p.get("title") or p.get("url", "") for p in fetched_pages]
        self._planner_decision(
            thought=f"Selected top {len(fetched_pages)} unique sources to read: {fetched_titles}.",
            chosen_action="fetch_top_sources",
            candidates=["fetch_top_sources", "fetch_all_results", "skip_fetching"],
            rejected_actions=["fetch_all_results", "skip_fetching"],
            confidence=0.8,
            iteration=2,
        )

        # 4. Summarize into a cited report.
        report_system = (
            "You are a research writer. Given a topic and a set of web pages, "
            "write a concise markdown report with citations. For each claim, "
            "cite the source URL in parentheses. If sources conflict, note it."
        )
        report_prompt = f"Topic: {task}\n\nSources:\n{json.dumps(fetched_pages, indent=2, default=str)}\n\nWrite the report."
        final_report = await self._llm_chat(report_system, report_prompt, name="write_report")

        self._planner_decision(
            thought="Synthesized fetched sources into a cited markdown report.",
            chosen_action="write_report",
            candidates=["write_report", "list_sources_only", "return_raw_pages"],
            rejected_actions=["list_sources_only", "return_raw_pages"],
            confidence=0.85,
            iteration=3,
        )

        return final_report

    async def _tool_web_search(self, query: str) -> list[dict[str, Any]]:
        """Search DuckDuckGo (no API key)."""
        if DDGS is None:
            raise RuntimeError("duckduckgo-search is not installed")

        def _search():
            with DDGS() as ddgs:
                return [
                    {"title": r["title"], "href": r["href"], "body": r["body"]}
                    for r in ddgs.text(query, max_results=5)
                ]

        return await asyncio.to_thread(_search)

    async def _tool_fetch_page(self, url: str) -> str:
        """Fetch a page as markdown via r.jina.ai (no API key)."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://r.jina.ai/{url}",
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text[:8000]

    def _extract_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
