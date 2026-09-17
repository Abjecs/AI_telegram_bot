from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, timezone

import pandas as pd

from config import *
from trading.ai import confirm_signal
from trading.bybit import BybitClient, BybitError
from trading.indicators import enrich
from trading.state import append_journal, load, save
from trading.indicators import enrich
from trading.strategy import evaluate

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self.client = BybitClient()
        self.running = False
        self.last_signal = None
        self.last_error = ""
        self.state = load()
        self.trades_today = int(self.state.get("trades_today", 0))
        self.realized_today = float(self.state.get("realized_today", 0.0))
        self.last_cycle = None
        self.last_trade_at = None
        self.last_candle = 0
        self.paper_position = self.state.get("position")
        self._lock = asyncio.Lock()
        self.qty_step = 0.001
        self.min_qty = 0.001
        self.max_leverage = None
        self.day = date.fromisoformat(self.state.get("day", date.today().isoformat()))

    async def start(self):
        self.running = True
        await self.client.start()
        self._reset_day()
        try:
            instrument = await self.client.instrument(SYMBOL)
            lot = instrument.get("lotSizeFilter", {})
            self.qty_step = float(lot.get("qtyStep", self.qty_step))
            self.min_qty = float(lot.get("minOrderQty", self.min_qty))
            leverage_filter = instrument.get("leverageFilter", {})
            if leverage_filter.get("maxLeverage") is not None:
                self.max_leverage = float(leverage_filter["maxLeverage"])
                if LEVERAGE > self.max_leverage:
                    raise RuntimeError(f"Configured leverage {LEVERAGE}x exceeds Bybit maximum {self.max_leverage}x for {SYMBOL}")
        except Exception as exc:
            logger.warning("Instrument load failed: %s", exc)
        logger.info("Trading engine started symbol=%s dry_run=%s leverage=%sx", SYMBOL, DRY_RUN, LEVERAGE)

    async def stop(self):
        self.running = False
        await self.client.close()

    def _persist(self):
        self.state["day"] = self.day.isoformat()
        self.state["trades_today"] = self.trades_today
        self.state["realized_today"] = self.realized_today
        self.state["position"] = self.paper_position
        save(self.state)

    def _round_qty(self, quantity: float) -> float:
        if self.qty_step <= 0:
            return quantity
        return math.floor(quantity / self.qty_step) * self.qty_step

    async def _equity(self) -> float:
        if CAPITAL_USDT > 0:
            return CAPITAL_USDT
        return await self.client.balance()

    def _reset_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day = today
            self.trades_today = 0
            self.realized_today = 0.0
            self.last_trade_at = None
            self._persist()

    def _daily_loss_limit(self, equity: float) -> float:
        limits = []
        if MAX_DAILY_LOSS_PCT > 0:
            limits.append(equity * MAX_DAILY_LOSS_PCT / 100.0)
        if MAX_DAILY_LOSS_USDT > 0:
            limits.append(MAX_DAILY_LOSS_USDT)
        return min(limits) if limits else 0.0

    def _cooldown(self) -> bool:
        if not self.last_trade_at:
            return False
        age = (datetime.now(timezone.utc) - self.last_trade_at).total_seconds()
        return age < COOLDOWN_MINUTES * 60

    def _microstructure_ok(self, ticker: dict, book: dict) -> bool:
        bid = float(ticker.get("bid1Price", 0)); ask = float(ticker.get("ask1Price", 0))
        if bid <= 0 or ask <= bid: return False
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid * 100
        if spread > MAX_SPREAD_PCT: return False
        bids = sum(float(x[1]) for x in book.get("b", [])[:10]); asks = sum(float(x[1]) for x in book.get("a", [])[:10])
        return bids + asks > 0

    def _risk_levels(self, signal):
        entry = float(signal.entry); stop = float(signal.stop); stop_distance = abs(entry - stop)
        if stop_distance <= 0: return entry, stop, stop, 0.0
        take_distance = stop_distance * 1.5
        take = entry + take_distance if signal.side == "Buy" else entry - take_distance
        return entry, stop, take, 1.5

    async def cycle(self):
        async with self._lock:
            self.last_cycle = datetime.now(timezone.utc)
            self._reset_day()
            try:
                equity = await self._equity(); daily_limit = self._daily_loss_limit(equity)
                if not TRADING_ENABLED or self.trades_today >= MAX_TRADES_PER_DAY: return
                if daily_limit > 0 and self.realized_today <= -daily_limit: return
                existing = None if DRY_RUN else await self.client.position(SYMBOL)
                if existing or self.paper_position or self._cooldown(): return
                k5, k15 = await asyncio.gather(self.client.klines(SYMBOL, "5", 250), self.client.klines(SYMBOL, "15", 250))
                df5 = self._closed(enrich(self._df(k5))); df15 = self._closed(enrich(self._df(k15)))
                if len(df5) < 210 or len(df15) < 210: return
                candle = int(df5.iloc[-1].start)
                if candle == self.last_candle: return
                self.last_candle = candle
                latest = df5.iloc[-1]; atr_pct = float(latest.atr_pct)
                if not (MIN_ATR_PCT <= atr_pct <= MAX_ATR_PCT): return
                ticker, book = await asyncio.gather(self.client.ticker(SYMBOL), self.client.orderbook(SYMBOL, 25))
                if not self._microstructure_ok(ticker, book): return
                signal = evaluate(df5, df15); self.last_signal = signal
                if not signal: return
                entry, stop, take, rr = self._risk_levels(signal)
                bids = sum(float(x[1]) for x in book.get("b", [])[:10]); asks = sum(float(x[1]) for x in book.get("a", [])[:10])
                imbalance = bids / (bids + asks) if bids + asks else 0.5
                if signal.side == "Buy" and imbalance < 0.42: return
                if signal.side == "Sell" and imbalance > 0.58: return
                spread_pct = abs(float(ticker["ask1Price"]) - float(ticker["bid1Price"])) / max(float(ticker["lastPrice"]), 1e-9) * 100
                funding = await self.client.funding(SYMBOL); funding_rate = float(funding.get("fundingRate", 0) or 0)
                ai_ok, ai_reason = await confirm_signal({"symbol": SYMBOL, "side": signal.side, "score": signal.score, "entry": entry, "stop": stop, "take": take, "rsi_5m": float(latest.rsi), "adx_5m": float(latest.adx), "atr_pct_5m": atr_pct, "volume_ratio": float(latest.vol_ratio), "vwap": float(latest.vwap), "orderbook_imbalance": imbalance, "spread_pct": spread_pct, "funding_rate": funding_rate, "reward_risk": rr, "reason": signal.reason})
                if not ai_ok: return
                risk_amount = equity * RISK_PER_TRADE_PCT / 100.0
                stop_distance = abs(entry - stop)
                quantity = self._round_qty(risk_amount / max(stop_distance, 1e-9))
                max_notional = equity * MAX_POSITION_NOTIONAL_PCT / 100.0 * LEVERAGE
                quantity = min(quantity, self._round_qty(max_notional / max(entry, 1e-9)))
                if quantity < self.min_qty: return
                now = datetime.now(timezone.utc); self.last_trade_at = now; self.trades_today += 1
                expected_loss = stop_distance * quantity; expected_profit = abs(take - entry) * quantity
                if DRY_RUN:
                    self.paper_position = {"side": signal.side, "qty": quantity, "entry": entry, "stop": stop, "take": take, "risk_usdt": expected_loss, "target_usdt": expected_profit, "leverage": LEVERAGE, "opened_at": now.isoformat()}
                    append_journal(self.state, "OPEN", self.paper_position | {"symbol": SYMBOL, "ai_reason": ai_reason, "rr": rr})
                else:
                    await self.client.set_leverage(SYMBOL, LEVERAGE)
                    await self.client.create_market_order(SYMBOL, signal.side, self._fmt_qty(quantity), self._fmt_price(stop), self._fmt_price(take))
                    append_journal(self.state, "LIVE_OPEN", {"symbol": SYMBOL, "side": signal.side, "qty": quantity, "entry": entry, "stop": stop, "take": take, "rr": rr})
                self._persist()
            except BybitError as exc:
                self.last_error = str(exc); logger.exception("Bybit cycle error")
            except Exception as exc:
                self.last_error = str(exc); logger.exception("Trading cycle error")

    async def paper_monitor(self, price: float):
        position = self.paper_position
        if not position: return
        side = position["side"]
        hit = (side == "Buy" and (price <= position["stop"] or price >= position["take"])) or (side == "Sell" and (price >= position["stop"] or price <= position["take"]))
        if not hit: return
        take_hit = (side == "Buy" and price >= position["take"]) or (side == "Sell" and price <= position["take"])
        exit_price = position["take"] if take_hit else position["stop"]
        pnl = (exit_price - position["entry"]) * position["qty"] * (1 if side == "Buy" else -1)
        self.realized_today += pnl
        append_journal(self.state, "CLOSE", {**position, "exit": exit_price, "pnl": pnl, "result": "TP" if take_hit else "SL"})
        self.paper_position = None
        self._persist()
        logger.info("PAPER CLOSE pnl=%.4f", pnl)

    @staticmethod
    def _closed(df: pd.DataFrame) -> pd.DataFrame: return df.iloc[:-1].copy() if len(df) else df
    @staticmethod
    def _df(rows):
        rows = list(reversed(rows))
        return pd.DataFrame(rows, columns=["start", "open", "high", "low", "close", "volume", "turnover"]).astype({c: float for c in ["open", "high", "low", "close", "volume", "turnover"]})
    @staticmethod
    def _fmt_qty(quantity): return f"{quantity:.8f}".rstrip("0").rstrip(".")
    @staticmethod
    def _fmt_price(price): return f"{price:.8f}".rstrip("0").rstrip(".")

    async def run(self):
        await self.start()
        try:
            while self.running:
                if DRY_RUN:
                    try:
                        ticker = await self.client.ticker(SYMBOL); await self.paper_monitor(float(ticker["lastPrice"]))
                    except Exception: pass
                await self.cycle(); await asyncio.sleep(POLL_SECONDS)
        finally: await self.stop()

    async def status(self):
        balance = position = None
        try:
            if TRADING_ENABLED and not DRY_RUN:
                balance, position = await asyncio.gather(self.client.balance(), self.client.position(SYMBOL))
        except Exception as exc: self.last_error = str(exc)
        return {"symbol": SYMBOL, "dry_run": DRY_RUN, "trading_enabled": TRADING_ENABLED, "capital": CAPITAL_USDT if CAPITAL_USDT > 0 else balance, "position": position or self.paper_position, "trades_today": self.trades_today, "realized_today": self.realized_today, "last_cycle": self.last_cycle.isoformat() if self.last_cycle else None, "last_error": self.last_error}
