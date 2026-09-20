"""Trip Planner agent.

Given a destination, dates, budget and preferences, it reasons over weather,
web search results, and local constraints to propose a day-by-day itinerary.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx

from .base import BaseAgent


try:
    from ddgs import DDGS
except Exception:  # pragma: no cover - dependency may be missing in some envs
    DDGS = None


class TripPlannerAgent(BaseAgent):
    name = "trip-planner-agent"
    display_name = "Trip Planner"
    description = "Reasons over weather, search, and budget to build an itinerary."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # 1. Extract structured trip parameters.
        extract_system = (
            "You are a trip-parameter extractor. Given a free-text request, respond "
            "with valid JSON only and no markdown fences. Infer missing fields when "
            "possible. Fields: destination (string), start_date (YYYY-MM-DD or null), "
            "end_date (YYYY-MM-DD or null), budget_usd (number or null), "
            "travelers (number or null), interests (list of strings or null), "
            "notes (string or null)."
        )
        extract_raw = await self._llm_chat(
            extract_system, f"Extract trip details from:\n\n{task}", name="extract_parameters"
        )
        try:
            params = self._extract_json(extract_raw)
        except Exception:
            params = {}

        destination = params.get("destination") or task.strip()
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        budget = params.get("budget_usd")
        travelers = params.get("travelers", 1)
        interests = params.get("interests") or []
        notes = params.get("notes") or ""

        # Record the parameter-extraction decision.
        self._planner_decision(
            thought=f"Extracted trip parameters from natural language: destination={destination}, "
            f"budget=${budget}, travelers={travelers}, interests={interests}.",
            chosen_action="parse_parameters",
            candidates=["parse_parameters", "ask_clarification"],
            rejected_actions=["ask_clarification"],
            confidence=0.85,
            iteration=1,
        )

        # 2. Gather evidence in parallel: weather + top attractions/activities.
        weather_task = self._tool("weather_forecast", {"destination": destination})
        search_task = self._tool("search_activities", {
            "destination": destination,
            "interests": interests,
            "notes": notes,
        })
        weather, activities = await asyncio.gather(weather_task, search_task, return_exceptions=True)

        # Normalize exceptions to error dicts so the planner still runs.
        if isinstance(weather, Exception):
            weather = {"error": str(weather)}
        if isinstance(activities, Exception):
            activities = {"error": str(activities)}

        # Record the evidence-gathering decision.
        self._planner_decision(
            thought="Fetched weather forecast and candidate activities in parallel. "
            "Will use weather to pick dry, mild days and activities to match interests.",
            chosen_action="fetch_weather_and_activities",
            candidates=["fetch_weather_and_activities", "skip_weather", "skip_activities"],
            rejected_actions=["skip_weather", "skip_activities"],
            confidence=0.9,
            iteration=2,
        )

        # 3. Build itinerary with explicit reasoning.
        plan_system = (
            "You are a careful trip planner. Given destination, dates, budget, travelers, "
            "interests, weather forecast, and a list of candidate activities, produce a "
            "day-by-day itinerary. Respond with valid JSON only and no markdown fences. "
            "Include: brief_reasoning (string explaining the biggest trade-offs), "
            "total_estimated_cost_usd (number or null), days (list; each day has "
            "date, morning/afternoon/evening activities with cost_usd each, weather_note, "
            "and why_this_order). If weather or budget blocks something, explain the "
            "decision in the activity's notes."
        )
        plan_prompt = (
            f"Destination: {destination}\n"
            f"Dates: {start_date} to {end_date}\n"
            f"Travelers: {travelers}\n"
            f"Budget USD: {budget}\n"
            f"Interests: {', '.join(interests) if interests else 'general sightseeing'}\n"
            f"Notes: {notes}\n\n"
            f"Weather forecast:\n{json.dumps(weather, indent=2, default=str)}\n\n"
            f"Candidate activities:\n{json.dumps(activities, indent=2, default=str)}\n\n"
            "Plan the itinerary."
        )
        plan_raw = await self._llm_chat(plan_system, plan_prompt, name="plan_itinerary")

        try:
            plan = self._extract_json(plan_raw)
            if isinstance(plan, list):
                # Some models return the day list directly; wrap it in the expected dict.
                plan = {"days": plan, "brief_reasoning": "", "total_estimated_cost_usd": None}
            if not isinstance(plan, dict):
                plan = {"brief_reasoning": "Planner returned an unexpected shape.", "days": [], "total_estimated_cost_usd": None}
        except Exception:
            plan = {"brief_reasoning": "Could not parse planner JSON.", "days": [], "total_estimated_cost_usd": None}

        # Record the itinerary decision.
        reasoning = plan.get("brief_reasoning", "")
        total = plan.get("total_estimated_cost_usd")
        budget_status = "under_budget"
        if budget and total and total > budget:
            budget_status = "over_budget"
        elif budget and total and total > budget * 0.9:
            budget_status = "near_budget"

        self._planner_decision(
            thought=reasoning or "Built a day-by-day itinerary from weather and candidate activities.",
            chosen_action="select_itinerary",
            candidates=["select_itinerary", "reduce_days", "drop_expensive_activities"],
            rejected_actions=["reduce_days", "drop_expensive_activities"]
            if budget_status == "under_budget"
            else ["select_itinerary"],
            confidence=0.8,
            iteration=3,
            budget_status=budget_status,
        )

        # 4. Render a clean markdown report.
        reasoning = plan.get("brief_reasoning", "")
        days = plan.get("days", [])
        total = plan.get("total_estimated_cost_usd")

        lines: list[str] = []
        lines.append(f"# Trip Plan: {destination}")
        if reasoning:
            lines.append(f"\n## Reasoning\n{reasoning}")
        if total is not None:
            lines.append(f"\n## Estimated total cost: ${total:,.2f} USD")
            if budget:
                remaining = budget - total
                lines.append(f"**Budget:** ${budget:,.2f} | **Remaining:** ${remaining:,.2f}")
        lines.append("")

        for day in days:
            date = day.get("date") or "Day"
            lines.append(f"### {date}")
            lines.append(f"*Weather note:* {day.get('weather_note', 'No weather note')}")
            if day.get("why_this_order"):
                lines.append(f"*Order rationale:* {day['why_this_order']}")
            for slot in ("morning", "afternoon", "evening"):
                slot_value = day.get(slot)
                if not slot_value:
                    continue
                # The LLM may return either a single activity dict or a list
                # of activities for each time slot; render both shapes safely.
                activities = slot_value if isinstance(slot_value, list) else [slot_value]
                for activity in activities:
                    if not isinstance(activity, dict):
                        continue
                    title = activity.get("title") or activity.get("name", "Unnamed activity")
                    cost = activity.get("cost_usd")
                    note = activity.get("notes", "")
                    cost_str = f" (${cost:,.2f})" if cost is not None else ""
                    lines.append(f"- **{slot.capitalize()}:** {title}{cost_str}")
                    if note:
                        lines.append(f"  - {note}")
            lines.append("")

        if not days:
            lines.append("_No day-by-day plan could be generated from the available data._")

        return "\n".join(lines)

    async def _tool_weather_forecast(self, destination: str) -> dict[str, Any]:
        """Fetch a 7-day daily weather forecast for the destination."""
        async with httpx.AsyncClient(timeout=20) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": destination, "count": 1},
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
            results = geo_data.get("results") or []
            if not results:
                raise ValueError(f"Could not geocode destination: {destination}")

            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
            timezone = results[0].get("timezone", "UTC")

            forecast_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": timezone,
                    "forecast_days": 7,
                },
            )
            forecast_resp.raise_for_status()
            data = forecast_resp.json().get("daily", {})
            days = []
            dates = data.get("time", [])
            for i, date in enumerate(dates):
                days.append({
                    "date": date,
                    "weather_code": data.get("weather_code", [])[i] if i < len(data.get("weather_code", [])) else None,
                    "temp_max_c": data.get("temperature_2m_max", [])[i] if i < len(data.get("temperature_2m_max", [])) else None,
                    "temp_min_c": data.get("temperature_2m_min", [])[i] if i < len(data.get("temperature_2m_min", [])) else None,
                    "precipitation_mm": data.get("precipitation_sum", [])[i] if i < len(data.get("precipitation_sum", [])) else None,
                })
            return {"destination": destination, "timezone": timezone, "daily": days}

    async def _tool_search_activities(
        self,
        destination: str,
        interests: list[str] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Search the web for things to do in the destination."""
        if DDGS is None:
            raise RuntimeError("duckduckgo-search is not installed")

        queries = [f"best things to do in {destination}"]
        for interest in (interests or []):
            queries.append(f"{interest} in {destination}")
        if notes:
            queries.append(f"{destination} travel guide {notes}")

        all_hits: list[dict[str, Any]] = []
        seen = set()

        def _search(q: str) -> list[dict[str, Any]]:
            with DDGS() as ddgs:
                return [
                    {"title": r["title"], "href": r["href"], "body": r["body"]}
                    for r in ddgs.text(q, max_results=5)
                ]

        for query in queries[:3]:
            hits = await asyncio.to_thread(_search, query)
            for h in hits:
                if h["href"] in seen:
                    continue
                seen.add(h["href"])
                all_hits.append(h)
                if len(all_hits) >= 8:
                    break
            if len(all_hits) >= 8:
                break

        return {"destination": destination, "activities": all_hits[:8]}

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
