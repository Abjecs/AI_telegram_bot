from __future__ import annotations

import json
import aiohttp

from config import AI_ENABLED, AI_FAIL_CLOSED, AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL


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


async def analyze_market(context: dict) -> dict | None:
    if not AI_ENABLED:
        return None
    if not OPENAI_API_KEY:
        if AI_FAIL_CLOSED:
            raise RuntimeError("OpenAI key is missing")
        return None

    instructions = (
        "You are the decision layer of a crypto day-trading bot. Analyze only the supplied market snapshot. "
        "You may choose LONG, SHORT, or NO_TRADE. If a trade is justified, choose a realistic LIMIT entry that "
        "has a reasonable chance to rest on the book rather than crossing it. Set stop and take yourself using market "
        "structure, volatility, liquidity and the user's required reward/risk ratio. The hard constraints in the input "
        "cannot be violated. Risk score is 1-10 where 10 is highest risk. Do not invent news or market data. "
        "Do not place, request, or simulate an order. Return only the requested structured object."
    )
    user = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
    payload = {
        "model": AI_MODEL,
        "store": False,
        "instructions": instructions,
        "input": user,
        "text": {"format": {"type": "json_schema", "name": "trade_proposal", "strict": True, "schema": SCHEMA}},
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            OPENAI_BASE_URL.rstrip("/") + "/responses",
            json=payload,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                message = data.get("error", {}).get("message", "request failed") if isinstance(data, dict) else "request failed"
                raise RuntimeError(f"AI HTTP {response.status}: {message}")

    text = data.get("output_text", "")
    if not text:
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text = content.get("text", "")
                    break
    if not text:
        raise RuntimeError("AI returned no structured output")
    result = json.loads(text)
    result["risk_score"] = int(result["risk_score"])
    result["confidence"] = int(result["confidence"])
    return result
