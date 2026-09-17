from __future__ import annotations

import os


def _int(name: str, default: int, minimum: int = 0) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
if TELEGRAM_ENABLED and not TELEGRAM_TOKEN:
    raise RuntimeError("Required environment variable is missing: TELEGRAM_TOKEN")

PORT = _int("PORT", 8080, 1)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "").strip()
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "").strip()
BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com").strip()
BYBIT_RECV_WINDOW = _int("BYBIT_RECV_WINDOW", 5000, 1000)

# User-facing trading controls. The AI/engine decides technical parameters.
SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}
LEVERAGE = _int("LEVERAGE", 3, 1)
MAX_DAILY_LOSS_PCT = _float("MAX_DAILY_LOSS_PCT", 4.0, 0.01)
TARGET_RR = _float("TARGET_RR", 1.5, 0.5)
MAX_TRADES_PER_DAY = _int("MAX_TRADES_PER_DAY", 6, 1)
COOLDOWN_MINUTES = _int("COOLDOWN_MINUTES", 20, 0)
POLL_SECONDS = _float("POLL_SECONDS", 20.0, 5.0)
MAX_AI_RISK_SCORE = _int("MAX_AI_RISK_SCORE", 6, 1)

# Internal safety/market defaults. These are intentionally not exposed in /help.
RISK_PER_TRADE_PCT = _float("RISK_PER_TRADE_PCT", 1.0, 0.01)
MAX_POSITION_NOTIONAL_PCT = _float("MAX_POSITION_NOTIONAL_PCT", 100.0, 1.0)
MAX_SPREAD_PCT = _float("MAX_SPREAD_PCT", 0.08)
MIN_ATR_PCT = _float("MIN_ATR_PCT", 0.08)
MAX_ATR_PCT = _float("MAX_ATR_PCT", 3.0)
AI_REANALYSIS_MINUTES = _int("AI_REANALYSIS_MINUTES", 15, 1)
PROPOSAL_EXPIRY_SECONDS = _int("PROPOSAL_EXPIRY_SECONDS", 120, 30)
ENTRY_MAX_MOVE_ATR = _float("ENTRY_MAX_MOVE_ATR", 0.35, 0.05)
NEWS_CACHE_MINUTES = _int("NEWS_CACHE_MINUTES", 30, 1)

AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
AI_FAIL_CLOSED = os.getenv("AI_FAIL_CLOSED", "true").lower() in {"1", "true", "yes", "on"}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-5.6-luna").strip()

if TRADING_ENABLED and not DRY_RUN and (not BYBIT_API_KEY or not BYBIT_API_SECRET):
    raise RuntimeError("LIVE trading requires BYBIT_API_KEY and BYBIT_API_SECRET")
