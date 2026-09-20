"""Paper Trade Signal agent.

Given a ticker/coin and recent news context, fetches market data and news,
reasons over price trend + sentiment, then emits a buy/sell/hold signal
with a short rationale and a paper position size.
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


class TradeSignalAgent(BaseAgent):
    name = "trade-signal-agent"
    display_name = "Paper Trade Signal"
    description = "Reasons over price data and news to emit a buy/sell/hold signal."

    async def execute(self, task: str, clarifications: list[str]) -> str:
        # 1. Extract ticker/symbol and any constraints.
        extract_system = (
            "You are a finance intent extractor. Given a user message, respond with "
            "valid JSON only and no markdown fences. Fields: symbol (uppercase ticker "
            "or coin like BTC), asset_type ('stock' or 'crypto' or null), risk_profile "
            "('conservative', 'moderate', 'aggressive' or null), context (string or null)."
        )
        extract_raw = await self._llm_chat(extract_system, task, name="extract_symbol")
        try:
            params = self._extract_json(extract_raw)
        except Exception:
            params = {}

        symbol = (params.get("symbol") or task.strip()).upper()
        asset_type = params.get("asset_type")
        risk_profile = params.get("risk_profile") or "moderate"
        context = params.get("context") or ""

        self._planner_decision(
            thought=f"Extracted trade request: symbol={symbol}, asset_type={asset_type or 'inferred'}, "
            f"risk_profile={risk_profile}.",
            chosen_action="parse_trade_request",
            candidates=["parse_trade_request", "ask_clarification"],
            rejected_actions=["ask_clarification"],
            confidence=0.85,
            iteration=1,
        )

        # 2. Gather evidence: price + news.
        price_task = self._tool("fetch_price", {"symbol": symbol, "asset_type": asset_type})
        news_task = self._tool("search_news", {"symbol": symbol, "context": context})
        price, news = await asyncio.gather(price_task, news_task, return_exceptions=True)

        if isinstance(price, Exception):
            price = {"error": str(price)}
        if isinstance(news, Exception):
            news = {"error": str(news)}

        self._planner_decision(
            thought="Fetched price/trend and recent news in parallel. Will weigh trend against "
            "sentiment before emitting a conservative signal.",
            chosen_action="fetch_price_and_news",
            candidates=["fetch_price_and_news", "skip_news", "skip_price"],
            rejected_actions=["skip_news", "skip_price"],
            confidence=0.9,
            iteration=2,
        )

        # 3. Reason to a decision.
        decide_system = (
            "You are a disciplined paper-trading analyst. Given market data and recent "
            "news, decide one of BUY, SELL, or HOLD. Respond with valid JSON only and "
            "no markdown fences. Include: signal (BUY/SELL/HOLD), confidence (0-1), "
            "reasoning (string), key_evidence (list of short strings), position_size_usd "
            "(number or null), and stop_loss_usd (number or null). Be conservative: "
            "only issue BUY if both trend and sentiment support it; issue SELL only if "
            "there is clear negative catalyst."
        )
        decide_prompt = (
            f"Symbol: {symbol}\n"
            f"Asset type: {asset_type or 'unknown'}\n"
            f"Risk profile: {risk_profile}\n"
            f"Context: {context}\n\n"
            f"Market data:\n{json.dumps(price, indent=2, default=str)}\n\n"
            f"News:\n{json.dumps(news, indent=2, default=str)}\n\n"
            "Make a decision."
        )
        decide_raw = await self._llm_chat(decide_system, decide_prompt, name="decide_signal")

        try:
            decision = self._extract_json(decide_raw)
        except Exception:
            decision = {
                "signal": "HOLD",
                "confidence": 0.0,
                "reasoning": "Could not parse decision JSON.",
                "key_evidence": [],
                "position_size_usd": None,
                "stop_loss_usd": None,
            }

        signal = decision.get("signal", "HOLD")
        confidence = decision.get("confidence")
        reasoning = decision.get("reasoning", "")
        evidence = decision.get("key_evidence", [])
        position = decision.get("position_size_usd")
        stop = decision.get("stop_loss_usd")

        self._planner_decision(
            thought=reasoning or f"Emitted {signal} signal based on price and news evidence.",
            chosen_action=f"signal_{signal.lower()}",
            candidates=["signal_buy", "signal_sell", "signal_hold"],
            rejected_actions=[
                a for a in ("signal_buy", "signal_sell", "signal_hold")
                if a != f"signal_{signal.lower()}"
            ],
            confidence=confidence if confidence is not None else 0.5,
            iteration=3,
            risk_profile=risk_profile,
        )

        lines: list[str] = []
        lines.append(f"# Paper Trade Signal: {symbol}")
        lines.append(f"\n**Signal:** `{signal}`")
        if confidence is not None:
            lines.append(f"**Confidence:** {confidence:.0%}")
        if reasoning:
            lines.append(f"\n## Reasoning\n{reasoning}")
        if evidence:
            lines.append("\n## Key evidence")
            for item in evidence:
                lines.append(f"- {item}")

        lines.append("\n## Market data")
        if "error" in price:
            lines.append(f"- _Price data unavailable: {price['error']}_")
        else:
            for key, value in price.items():
                if key == "error":
                    continue
                if isinstance(value, float):
                    lines.append(f"- **{key}:** {value:,.4f}")
                else:
                    lines.append(f"- **{key}:** {value}")

        if position is not None:
            lines.append(f"\n**Suggested paper position:** ${position:,.2f}")
        if stop is not None:
            lines.append(f"**Suggested stop-loss:** ${stop:,.4f}")

        lines.append("\n*This is a paper trade for evaluation only — not financial advice.*")
        return "\n".join(lines)

    async def _tool_fetch_price(self, symbol: str, asset_type: str | None = None) -> dict[str, Any]:
        """Fetch latest price and recent trend."""
        # Try crypto first if the symbol looks like a coin or asset_type is crypto.
        looks_crypto = asset_type == "crypto" or symbol in {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA"}
        if looks_crypto:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params={
                            "ids": symbol.lower(),
                            "vs_currencies": "usd",
                            "include_24hr_change": "true",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json().get(symbol.lower(), {})
                    return {
                        "current_price_usd": data.get("usd"),
                        "change_24h_percent": data.get("usd_24h_change"),
                        "source": "coingecko",
                    }
            except Exception as exc:
                if asset_type == "crypto":
                    raise
                # Otherwise fall through and try stocks.

        # Stocks via Alpha Vantage if API key is set; otherwise use a public fallback.
        api_key = __import__("os").getenv("ALPHA_VANTAGE_API_KEY")
        if api_key:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": symbol,
                        "apikey": api_key,
                    },
                )
                resp.raise_for_status()
                quote = resp.json().get("Global Quote", {})
                return {
                    "current_price_usd": float(quote.get("05. price", 0)) or None,
                    "change_24h_percent": float(quote.get("10. change percent", "0%").replace("%", "")) or None,
                    "source": "alphavantage",
                }

        # Fallback: try a free public endpoint (CryptoCompare supports many symbols).
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USD",
                )
                resp.raise_for_status()
                data = resp.json()
                if "USD" in data:
                    return {
                        "current_price_usd": data.get("USD"),
                        "change_24h_percent": None,
                        "source": "cryptocompare",
                    }
        except Exception:
            pass

        raise RuntimeError(
            f"No price source available for {symbol}. Set ALPHA_VANTAGE_API_KEY or use a "
            "known crypto symbol (BTC, ETH, etc.)."
        )

    async def _tool_search_news(self, symbol: str, context: str = "") -> dict[str, Any]:
        """Search recent web headlines for the symbol/topic."""
        if DDGS is None:
            raise RuntimeError("duckduckgo-search is not installed")

        queries = [f"{symbol} latest news"]
        if context:
            queries.append(f"{symbol} {context}")

        all_hits: list[dict[str, Any]] = []
        seen = set()

        def _search(q: str) -> list[dict[str, Any]]:
            with DDGS() as ddgs:
                return [
                    {"title": r["title"], "href": r["href"], "body": r["body"]}
                    for r in ddgs.text(q, max_results=5)
                ]

        for query in queries[:2]:
            hits = await asyncio.to_thread(_search, query)
            for h in hits:
                if h["href"] in seen:
                    continue
                seen.add(h["href"])
                all_hits.append(h)
                if len(all_hits) >= 5:
                    break
            if len(all_hits) >= 5:
                break

        return {"symbol": symbol, "headlines": all_hits[:5]}

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[-1]
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
