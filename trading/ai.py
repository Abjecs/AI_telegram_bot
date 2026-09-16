from __future__ import annotations
import json
import aiohttp
from config import AI_ENABLED, AI_FAIL_CLOSED, AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL

async def confirm_signal(context: dict) -> tuple[bool,str]:
    if not AI_ENABLED: return True,"AI disabled"
    if not OPENAI_API_KEY: return (False,"OpenAI key is missing") if AI_FAIL_CLOSED else (True,"AI key missing; technical filters only")
    system=("You are a conservative crypto day-trading risk filter. Use ONLY supplied data. "
            "Return JSON only with decision LONG, SHORT, or NO_TRADE and a concise reason. "
            "Reject conflicting trend, excessive volatility, weak volume, poor reward/risk, or ambiguous setups. Never invent data.")
    payload={"model":AI_MODEL,"temperature":0,"response_format":{"type":"json_object"},"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(context,separators=(",",":"),ensure_ascii=False)}]}
    try:
        timeout=aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_BASE_URL.rstrip("/")+"/chat/completions",json=payload,headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"}) as r:
                data=await r.json(content_type=None)
                if r.status>=400: return False,f"AI HTTP {r.status}: {data.get('error',{}).get('message','request failed')}"
        text=data["choices"][0]["message"]["content"]
        parsed=json.loads(text)
        expected="LONG" if context["side"]=="Buy" else "SHORT"
        return parsed.get("decision")==expected,str(parsed.get("reason","no reason"))
    except Exception as exc:
        return False,f"AI unavailable: {exc}"
