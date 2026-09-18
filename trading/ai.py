from __future__ import annotations

import json
import logging

import aiohttp

from config import AI_ENABLED, AI_FAIL_CLOSED, AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["LONG", "SHORT", "NO_TRADE"]},
        "entry": {"type": "number"},
        "stop": {"type": "number"},
        "take": {"type": "number"},
        "risk_score": {"type": "integer", "minimum": 1, "maximum": 10},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "rationale": {"type": "string"},
        "invalidation": {"type": "string"},
    },
    "required": ["decision", "entry", "stop", "take", "risk_score", "confidence", "rationale", "invalidation"],
    "additionalProperties": False,
}

_warned_missing_key = False


def available() -> bool:
    return bool(AI_ENABLED and OPENAI_API_KEY)


async def analyze_market(context: dict) -> dict | None:
    global _warned_missing_key

    if not AI_ENABLED:
        return None

    if not OPENAI_API_KEY:
        if not _warned_missing_key:
            logger.warning("AI is enabled but OPENAI_API_KEY is not configured; AI proposals are disabled until a key is added.")
            _warned_missing_key = True
        # Fail closed means: no AI answer -> no trade. It must not crash the trading loop.
        return None

    instructions = (
        "You are the decision layer of a crypto day-trading bot. Analyze only the supplied market snapshot. "
        "Choose LONG, SHORT, or NO_TRADE. If a trade is justified, choose a realistic maker LIMIT entry. "
        "Set stop and take from market structure, volatility and liquidity. The hard constraints in the input "
        "cannot be violated. Risk score 1-10 means 10 is highest risk. Never invent news or data. "
        "Do not place or simulate orders. Return only the requested structured object."
    )
    user = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
    payload = {
        "model": AI_MODEL,
        "store": False,
        "instructions": instructions,
        "input": user,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "trade_proposal",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_BASE_URL.rstrip("/") + "/responses",
                json=payload,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    message = data.get("error", {}).get("message", "request failed") if isinstance(data, dict) else "request failed"
                    raise RuntimeError(f"AI HTTP {response.status}: {message}")
    except Exception as exc:
        # AI is a filter, never a reason for the Bybit/Telegram engine to crash.
        logger.warning("AI analysis unavailable: %s", exc)
        return None

    text = data.get("output_text", "")
    if not text:
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text", "")
                    break
            if text:
                break

    if not text:
        logger.warning("AI returned no structured output")
        return None

    try:
        result = json.loads(text)
        result["risk_score"] = int(result["risk_score"])
        result["confidence"] = int(result["confidence"])
        return result
    except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("AI returned invalid structured output: %s", exc)
        return None
