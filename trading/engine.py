from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

import pandas as pd

from config import (
    CAPITAL_USDT, DRY_RUN, LEVERAGE, MAX_DAILY_LOSS_USDT, MAX_POSITION_NOTIONAL_PCT,
    POLL_SECONDS, RISK_PER_TRADE_PCT, SYMBOL, TRADING_ENABLED,
)
from trading.ai import confirm_signal
from trading.bybit import BybitClient, BybitError
from trading.indicators import enrich
from trading.strategy import Signal, evaluate

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self) -> None:
        self.client = BybitClient()
        self.running = False
        self.last_signal: Signal | None = None
        self.last_error = ""
        self.trades_today = 0
        self.realized_today = 0.0
        self.last_cycle: datetime | None = None
        self._lock = asyncio.Lock()
        self.qty_step = 0.001
        self.min_qty = 0.001

    async def start(self) -> None:
        self.running = True
        await self.client.start()
        try:
            instrument = await self.client.instrument(SYMBOL)
            lot = instrument.get("lotSizeFilter", {})
            self.qty_step = float(lot.get("qtyStep", self.qty_step))
            self.min_qty = float(lot.get("minOrderQty", self.min_qty))
        except Exception as exc:
            logger.warning("Instrument load failed: %s", exc)
        logger.info("Trading engine started: symbol=%s dry_run=%s", SYMBOL, DRY_RUN)

    async def stop(self) -> None:
        self.running = False
        await self.client.close()

    def _round_qty(self, qty: float) -> float:
        if self.qty_step <= 0:
            return qty
        return math.floor(qty / self.qty_step) * self.qty_step

    async def _equity(self) -> float:
        if CAPITAL_USDT > 0:
            return CAPITAL_USDT
        return await self.client.balance()

    async def cycle(self) -> None:
        async with self._lock:
            self.last_cycle = datetime.now(timezone.utc)
            if not TRADING_ENABLED:
                return
            if MAX_DAILY_LOSS_USDT > 0 and self.realized_today <= -MAX_DAILY_LOSS_USDT:
                return
            try:
                existing = await self.client.position(SYMBOL)
                if existing:
                    return
                k5, k15 = await asyncio.gather(
                    self.client.klines(SYMBOL, "5", 250),
                    self.client.klines(SYMBOL, "15", 250),
                )
                df5 = self._df(k5)
                df15 = self._df(k15)
                signal = evaluate(enrich(df5), enrich(df15))
                self.last_signal = signal
                if not signal:
                    return
                ai_ok, ai_reason = await confirm_signal({
                    "symbol": SYMBOL, "side": signal.side, "score": signal.score,
                    "entry": signal.entry, "stop": signal.stop, "take": signal.take,
                    "rsi_5m": float(df5.iloc[-1].get("rsi", 50)) if "rsi" in df5 else None,
                    "reason": signal.reason,
                })
                if not ai_ok:
                    logger.info("Signal rejected by AI: %s", ai_reason)
                    return
                equity = await self._equity()
                risk_usdt = equity * RISK_PER_TRADE_PCT / 100
                stop_distance = abs(signal.entry - signal.stop)
                qty = self._round_qty(risk_usdt / stop_distance)
                max_notional = equity * MAX_POSITION_NOTIONAL_PCT / 100 * LEVERAGE
                qty = min(qty, self._round_qty(max_notional / signal.entry))
                if qty < self.min_qty:
                    logger.warning("Calculated qty %.8f below exchange minimum %.8f", qty, self.min_qty)
                    return
                if DRY_RUN:
                    self.trades_today += 1
                    logger.info("PAPER %s qty=%s entry=%.2f SL=%.2f TP=%.2f AI=%s", signal.side, qty, signal.entry, signal.stop, signal.take, ai_reason)
                    return
                await self.client.set_leverage(SYMBOL, LEVERAGE)
                await self.client.create_market_order(SYMBOL, signal.side, self._fmt_qty(qty), self._fmt_price(signal.stop), self._fmt_price(signal.take))
                self.trades_today += 1
                logger.info("LIVE %s qty=%s entry=%.2f SL=%.2f TP=%.2f AI=%s", signal.side, qty, signal.entry, signal.stop, signal.take, ai_reason)
            except BybitError as exc:
                self.last_error = str(exc)
                logger.exception("Bybit cycle error")
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Trading cycle error")

    @staticmethod
    def _df(rows: list[list[str]]) -> pd.DataFrame:
        rows = list(reversed(rows))
        return pd.DataFrame(rows, columns=["start","open","high","low","close","volume","turnover"]).astype({c: float for c in ["open","high","low","close","volume","turnover"]})

    @staticmethod
    def _fmt_qty(qty: float) -> str:
        return f"{qty:.8f}".rstrip("0").rstrip(".")

    @staticmethod
    def _fmt_price(price: float) -> str:
        return f"{price:.8f}".rstrip("0").rstrip(".")

    async def run(self) -> None:
        await self.start()
        try:
            while self.running:
                await self.cycle()
                await asyncio.sleep(POLL_SECONDS)
        finally:
            await self.stop()

    async def status(self) -> dict:
        balance = None
        position = None
        if not DRY_RUN and TRADING_ENABLED:
            try:
                balance, position = await asyncio.gather(self.client.balance(), self.client.position(SYMBOL))
            except Exception as exc:
                self.last_error = str(exc)
        return {
            "symbol": SYMBOL, "dry_run": DRY_RUN, "trading_enabled": TRADING_ENABLED,
            "capital": CAPITAL_USDT if CAPITAL_USDT > 0 else balance,
            "position": position, "trades_today": self.trades_today,
            "realized_today": self.realized_today,
            "last_cycle": self.last_cycle.isoformat() if self.last_cycle else None,
            "last_error": self.last_error,
        }
