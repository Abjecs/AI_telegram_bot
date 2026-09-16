from __future__ import annotations

import os


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


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


TELEGRAM_TOKEN = _required("TELEGRAM_TOKEN")
PORT = _int("PORT", 8080, 1)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "").strip()
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "").strip()
BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com").strip()
BYBIT_RECV_WINDOW = _int("BYBIT_RECV_WINDOW", 5000, 1000)

SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in {"1", "true", "yes", "on"}
CAPITAL_USDT = _float("CAPITAL_USDT", 0.0, 0.0)
RISK_PER_TRADE_PCT = _float("RISK_PER_TRADE_PCT", 0.5, 0.01)
MAX_POSITION_NOTIONAL_PCT = _float("MAX_POSITION_NOTIONAL_PCT", 100.0, 1.0)
MAX_DAILY_LOSS_USDT = _float("MAX_DAILY_LOSS_USDT", 0.0, 0.0)
LEVERAGE = _int("LEVERAGE", 3, 1)
POLL_SECONDS = _float("POLL_SECONDS", 20.0, 5.0)
MIN_SIGNAL_SCORE = _int("MIN_SIGNAL_SCORE", 6, 1)
ATR_STOP_MULTIPLIER = _float("ATR_STOP_MULTIPLIER", 1.5, 0.1)
ATR_TP_MULTIPLIER = _float("ATR_TP_MULTIPLIER", 2.5, 0.1)

AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-5.6-luna").strip()

if TRADING_ENABLED and not DRY_RUN and (not BYBIT_API_KEY or not BYBIT_API_SECRET):
    raise RuntimeError("LIVE trading requires BYBIT_API_KEY and BYBIT_API_SECRET")
