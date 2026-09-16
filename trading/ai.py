from __future__ import annotations

import json

import aiohttp

from config import AI_ENABLED, AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL


async def confirm_signal(context: dict) -> tuple[bool, str]:
    if not AI_ENABLED:
        return True, "AI confirmation disabled"
    if not OPENAI_API_KEY:
        return True, "AI key not configured; technical filters only"
    system = (
        "You are a conservative crypto day-trading signal filter. "
        "Return JSON only: {\"decision\":\"LONG\"|\"SHORT\"|\"NO_TRADE\",\"reason\":\"short reason\"}. "
        "Never invent market data. Reject weak, conflicting or low-quality setups."
    )
    payload = {
        "model": AI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(context, separators=(",", ":"), ensure_ascii=False)}],
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(OPENAI_BASE_URL.rstrip("/") + "/chat/completions", json=payload, headers=headers) as response:
            if response.status >= 400:
                return False, f"AI HTTP {response.status}"
            data = await response.json()
    parsed = json.loads(data["choices"][0]["message"]["content"])
    expected = "LONG" if context["side"] == "Buy" else "SHORT"
    return parsed.get("decision") == expected, str(parsed.get("reason", "no reason"))
