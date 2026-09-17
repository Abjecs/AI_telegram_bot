from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserTradingConfig:
    symbol: str
    leverage: int
    daily_loss_pct: float
    target_rr: float
    max_trades_per_day: int
    cooldown_minutes: int
    poll_seconds: float
    max_ai_risk_score: int
