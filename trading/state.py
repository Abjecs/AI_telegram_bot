from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path(os.getenv("TRADING_STATE_PATH", "/tmp/trading_state.json"))


def _default() -> dict[str, Any]:
    return {
        "day": datetime.now(timezone.utc).date().isoformat(),
        "trades_today": 0,
        "realized_today": 0.0,
        "position": None,
        "journal": [],
        "settings": {},
    }


def load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        base = _default()
        base.update(data)
        if not isinstance(base.get("settings"), dict):
            base["settings"] = {}
        return base
    except Exception:
        return _default()


def save(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def append_journal(data: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
    data.setdefault("journal", []).append({
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    })
    data["journal"] = data["journal"][-500:]
    save(data)
