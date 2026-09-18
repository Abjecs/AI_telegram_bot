from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
import uuid
from datetime import date, datetime, timezone

import pandas as pd

from config import *
from trading.ai import analyze_market
from trading.bybit import BybitClient, BybitError
from trading.indicators import enrich
from trading.state import append_journal, load, save
from trading.strategy import evaluate

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self):
        self.client = BybitClient()
        self.running = False
        self.last_signal = None
        self.last_error = ""
        self.last_cycle = None
        self.last_ai_at = 0.0
        self.last_ai_hash = ""
        self.last_candidate = None
        self.pending_proposal = None
        self.state = load()
        self.day = date.fromisoformat(self.state.get("day", date.today().isoformat()))
        self.trades_today = int(self.state.get("trades_today", 0))
        self.realized_today = float(self.state.get("realized_today", 0.0))
        self.starting_equity = float(self.state.get("starting_equity", 0.0))
        self.last_trade_at = datetime.fromisoformat(self.state["last_trade_at"]) if self.state.get("last_trade_at") else None
        self.pending_order = self.state.get("pending_order")
        self.exchange_trade = self.state.get("exchange_trade")
        self.live_armed = False
        self.event_callback = None
        self.paper_position = self.state.get("position")
        self.paper_capital = float(self.state.get("paper_capital", PAPER_CAPITAL_USDT))
        self.last_price = 0.0
        self.last_atr = 0.0
        self.qty_step = 0.001
        self.min_qty = 0.001
        self.tick_size = 0.01
        self._lock = asyncio.Lock()

    async def start(self):
        self.running = True
        await self.client.start()
        await self._load_instrument()
        try:
            equity = await self._equity()
            if equity > 0 and self.starting_equity <= 0:
                self.starting_equity = equity
                self._persist()
            logger.info("AI trading engine started symbol=%s mode=%s leverage=%sx equity=%.4f",
                        SYMBOL, TRADING_MODE, LEVERAGE, equity)
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Initial Bybit account check failed: %s", exc)

    async def _load_instrument(self):
        try:
            info = await self.client.instrument(SYMBOL)
            lot = info.get("lotSizeFilter", {})
            price = info.get("priceFilter", {})
            self.qty_step = float(lot.get("qtyStep", self.qty_step))
            self.min_qty = float(lot.get("minOrderQty", self.min_qty))
            self.tick_size = float(price.get("tickSize", self.tick_size))
            max_lev = info.get("leverageFilter", {}).get("maxLeverage")
            if max_lev is not None and LEVERAGE > float(max_lev):
                raise RuntimeError(f"Leverage {LEVERAGE}x exceeds Bybit maximum {max_lev}x for {SYMBOL}")
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Instrument load failed: %s", exc)

    async def stop(self):
        self.running = False
        await self.client.close()

    def _persist(self):
        self.state.update({
            "day": self.day.isoformat(), "trades_today": self.trades_today,
            "realized_today": self.realized_today, "starting_equity": self.starting_equity,
            "position": self.paper_position, "pending_order": self.pending_order,
            "exchange_trade": self.exchange_trade,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
            "paper_capital": self.paper_capital,
        })
        save(self.state)

    async def _equity(self):
        if TRADING_MODE == "PAPER":
            return self.paper_capital
        exchange_equity = await self.client.balance()
        return TRADE_CAPITAL_USDT if TRADE_CAPITAL_USDT > 0 else exchange_equity

    def _reset_day(self, equity):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day = today
            self.trades_today = 0
            self.realized_today = 0.0
            self.starting_equity = equity
            self.last_trade_at = None
            self.last_ai_hash = ""
            self.pending_proposal = None
            self._persist()
        elif self.starting_equity <= 0 and equity > 0:
            self.starting_equity = equity
            self._persist()

    def _daily_limit(self):
        return self.starting_equity * MAX_DAILY_LOSS_PCT / 100 if self.starting_equity > 0 else 0.0

    def _cooldown_active(self):
        return bool(self.last_trade_at and
                    (datetime.now(timezone.utc) - self.last_trade_at).total_seconds() < COOLDOWN_MINUTES * 60)

    def _round_qty(self, qty):
        if self.qty_step <= 0:
            return qty
        return math.floor(qty / self.qty_step) * self.qty_step

    @staticmethod
    def _round_price(price, tick):
        return round(math.floor(price / tick) * tick, 12) if tick > 0 else price

    @staticmethod
    def _fmt(value):
        return f"{value:.12f}".rstrip("0").rstrip(".")

    @staticmethod
    def _closed(df):
        return df.iloc[:-1].copy() if len(df) else df

    @staticmethod
    def _df(rows):
        return pd.DataFrame(
            list(reversed(rows)),
            columns=["start", "open", "high", "low", "close", "volume", "turnover"],
        ).astype({
            "start": float, "open": float, "high": float, "low": float,
            "close": float, "volume": float, "turnover": float,
        })

    def _microstructure(self, ticker, book):
        bid = float(ticker.get("bid1Price", 0) or 0)
        ask = float(ticker.get("ask1Price", 0) or 0)
        if bid <= 0 or ask <= bid:
            return False, 0.0, 0.5
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid * 100
        bids = sum(float(x[1]) for x in book.get("b", [])[:10])
        asks = sum(float(x[1]) for x in book.get("a", [])[:10])
        imbalance = bids / (bids + asks) if bids + asks else 0.5
        return spread <= MAX_SPREAD_PCT, spread, imbalance

    def _candidate_hash(self, signal, latest, ticker, imbalance):
        raw = "|".join([
            SYMBOL, signal.side, str(signal.score),
            f"{float(latest.close):.2f}", f"{float(latest['atr']):.2f}",
            f"{float(ticker.get('lastPrice', 0)):.2f}", f"{imbalance:.3f}",
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    def _ai_context(self, df5, df15, signal, ticker, book, funding, equity, imbalance, spread):
        def row(df):
            r = df.iloc[-1]
            return {
                "close": float(r.close), "ema20": float(r.ema20),
                "ema50": float(r.ema50), "ema200": float(r.ema200),
                "rsi": float(r.rsi), "macd": float(r.macd),
                "macd_signal": float(r.macd_signal), "adx": float(r.adx),
                "atr": float(r["atr"]), "atr_pct": float(r["atr_pct"]),
                "volume_ratio": float(r.vol_ratio), "vwap": float(r.vwap),
                "breakout_high": float(r.high20), "breakout_low": float(r.low20),
                "bb_upper": float(r.bb_upper), "bb_lower": float(r.bb_lower),
            }

        return {
            "symbol": SYMBOL,
            "timeframes": {"5m": row(df5), "15m": row(df15)},
            "candidate": {"side": signal.side, "score": signal.score, "reason": signal.reason},
            "ticker": {
                "last": float(ticker.get("lastPrice", 0)),
                "bid": float(ticker.get("bid1Price", 0)),
                "ask": float(ticker.get("ask1Price", 0)),
            },
            "orderbook": {
                "imbalance_top10": imbalance,
                "bids": book.get("b", [])[:10],
                "asks": book.get("a", [])[:10],
            },
            "funding_rate": float(funding.get("fundingRate", 0) or 0),
            "account_equity": equity,
            "hard_constraints": {
                "leverage": LEVERAGE,
                "daily_loss_limit_pct": MAX_DAILY_LOSS_PCT,
                "target_rr": TARGET_RR,
                "max_trades_today": MAX_TRADES_PER_DAY,
                "cooldown_minutes": COOLDOWN_MINUTES,
                "max_ai_risk_score": MAX_AI_RISK_SCORE,
            },
            "risk_policy": "Risk per trade is 1% of account equity unless a safety cap makes it smaller. Never exceed the daily loss limit.",
            "spread_pct": spread,
        }

    def _size_position(self, equity, entry, stop_distance):
        risk_amount = equity * RISK_PER_TRADE_PCT / 100
        qty = self._round_qty(risk_amount / max(stop_distance, 1e-9))
        max_notional = equity * MAX_POSITION_NOTIONAL_PCT / 100 * LEVERAGE
        return min(qty, self._round_qty(max_notional / max(entry, 1e-9)))

    async def _emit_event(self, text):
        if not text or not self.event_callback:
            return
        try:
            await self.event_callback(text)
        except Exception as exc:
            logger.warning("Trade notification failed: %s", exc)

    async def _handle_exchange_close(self):
        trade = self.exchange_trade
        if not trade:
            return
        try:
            closed = await self.client.closed_pnl(SYMBOL)
            if not closed:
                return
            item = closed[0]
            closed_at = int(item.get("updatedTime", 0) or 0)
            opened_at = int(trade.get("opened_at_ms", 0) or 0)
            if opened_at and closed_at and closed_at < opened_at:
                return
            pnl = float(item.get("closedPnl", 0) or 0)
            result = "TP" if pnl >= 0 else "SL/OTHER"
            payload = {
                **trade,
                "exit": float(item.get("avgExitPrice", 0) or 0),
                "pnl": pnl,
                "result": result,
                "closed_pnl": item,
            }
            append_journal(self.state, f"{TRADING_MODE}_CLOSE", payload)
            self.realized_today += pnl
            self.exchange_trade = None
            self._persist()
            await self._emit_event(
                f"{'🟢' if pnl >= 0 else '🔴'} {TRADING_MODE}: позиция закрыта.\n"
                f"{SYMBOL}\nРезультат: {result}\nP&L: {pnl:+.4f} USDT"
            )
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Exchange close check failed: %s", exc)

    async def cycle(self):
        async with self._lock:
            self.last_cycle = datetime.now(timezone.utc)
            try:
                equity = await self._equity()
                if equity <= 0:
                    return None
                self._reset_day(equity)

                # Existing orders/positions are always managed, even when new entries are OFF.
                if self.pending_order:
                    await self._monitor_pending_order()
                    return None

                if TRADING_MODE != "PAPER":
                    exchange_position = await self.client.position(SYMBOL)
                    if exchange_position:
                        if not self.exchange_trade:
                            self.exchange_trade = {
                                "side": exchange_position.get("side"),
                                "qty": float(exchange_position.get("size", 0) or 0),
                                "entry": float(exchange_position.get("avgPrice", 0) or 0),
                                "stop": float(exchange_position.get("stopLoss", 0) or 0),
                                "take": float(exchange_position.get("takeProfit", 0) or 0),
                                "opened_at_ms": int(time.time() * 1000),
                            }
                            self._persist()
                        return None
                    if self.exchange_trade:
                        await self._handle_exchange_close()
                        return None

                if self.paper_position:
                    ticker = await self.client.ticker(SYMBOL)
                    self.last_price = float(ticker.get("lastPrice", 0) or 0)
                    if self.last_price > 0:
                        await self.paper_monitor(self.last_price, ticker=ticker)
                    return None

                # OFF means: no new proposals. It does not abandon an existing position/order.
                if not TRADING_ENABLED or self.trades_today >= MAX_TRADES_PER_DAY:
                    return None
                if self._daily_limit() and self.realized_today <= -self._daily_limit():
                    return None
                if self._cooldown_active():
                    return None

                k5, k15 = await asyncio.gather(
                    self.client.klines(SYMBOL, "5", 250),
                    self.client.klines(SYMBOL, "15", 250),
                )
                df5 = self._closed(enrich(self._df(k5)))
                df15 = self._closed(enrich(self._df(k15)))
                if len(df5) < 20 or len(df15) < 20:
                    return None

                latest = df5.iloc[-1]
                self.last_price = float(latest.close)
                self.last_atr = float(latest["atr"])
                if not MIN_ATR_PCT <= float(latest["atr_pct"]) <= MAX_ATR_PCT:
                    return None

                ticker, book = await asyncio.gather(
                    self.client.ticker(SYMBOL),
                    self.client.orderbook(SYMBOL, 25),
                )
                ok, spread, imbalance = self._microstructure(ticker, book)
                if not ok:
                    return None

                signal = evaluate(df5, df15)
                self.last_signal = signal
                if not signal:
                    return None

                candidate_hash = self._candidate_hash(signal, latest, ticker, imbalance)
                now = time.time()
                if candidate_hash == self.last_ai_hash and now - self.last_ai_at < AI_REANALYSIS_MINUTES * 60:
                    return None

                funding = await self.client.funding(SYMBOL)
                result = await analyze_market(
                    self._ai_context(df5, df15, signal, ticker, book, funding, equity, imbalance, spread)
                )
                self.last_ai_at = now
                self.last_ai_hash = candidate_hash

                if not result or result.get("decision") == "NO_TRADE":
                    return None
                expected = "LONG" if signal.side == "Buy" else "SHORT"
                if result.get("decision") != expected:
                    return None

                risk_score = int(result["risk_score"])
                if not 1 <= risk_score <= 10 or risk_score > MAX_AI_RISK_SCORE:
                    return None

                entry = float(result["entry"])
                stop = float(result["stop"])
                # AI may suggest TP, but the bot owns the hard RR constraint.
                stop_distance = abs(entry - stop)
                if min(entry, stop) <= 0 or stop_distance <= 0:
                    return None
                take = entry + stop_distance * TARGET_RR if signal.side == "Buy" else entry - stop_distance * TARGET_RR
                reward_distance = abs(take - entry)
                if reward_distance / stop_distance + 1e-9 < TARGET_RR:
                    return None
                if signal.side == "Buy" and not stop < entry < take:
                    return None
                if signal.side == "Sell" and not take < entry < stop:
                    return None

                qty = self._size_position(equity, entry, stop_distance)
                if qty < self.min_qty:
                    return None

                proposal = {
                    "id": uuid.uuid4().hex[:12], "symbol": SYMBOL, "side": signal.side,
                    "entry": entry, "stop": stop, "take": take, "qty": qty,
                    "risk_score": risk_score, "confidence": int(result.get("confidence", 0)),
                    "rationale": str(result.get("rationale", "")),
                    "invalidation": str(result.get("invalidation", "")),
                    "rr": reward_distance / stop_distance, "equity": equity,
                    "created_at": time.time(), "candidate_hash": candidate_hash,
                }
                self.pending_proposal = proposal
                self.last_candidate = proposal
                return proposal

            except BybitError as exc:
                self.last_error = str(exc)
                logger.error("Bybit cycle error: %s", exc)
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Trading cycle error")
            return None

    async def confirm_proposal(self, proposal_id):
        async with self._lock:
            proposal = self.pending_proposal
            if not proposal or proposal.get("id") != proposal_id:
                return False, "Предложение отсутствует или устарело."
            if time.time() - float(proposal["created_at"]) > PROPOSAL_EXPIRY_SECONDS:
                self.pending_proposal = None
                return False, "Предложение истекло. Нужен новый анализ рынка."

            # Final hard safety gate. AI cannot bypass these limits.
            if not TRADING_ENABLED:
                return False, "Новые входы сейчас выключены."
            if self.trades_today >= MAX_TRADES_PER_DAY:
                return False, "Достигнут лимит сделок на сегодня."
            if self._daily_limit() and self.realized_today <= -self._daily_limit():
                return False, "Достигнут дневной лимит убытка."
            if self._cooldown_active():
                return False, "Ещё действует пауза между сделками."
            if self.pending_order:
                return False, "Уже есть активная заявка."
            if TRADING_MODE != "PAPER" and await self.client.position(SYMBOL):
                return False, "По паре уже есть открытая позиция."

            try:
                ticker, _ = await asyncio.gather(
                    self.client.ticker(SYMBOL), self.client.orderbook(SYMBOL, 10)
                )
                bid = float(ticker["bid1Price"])
                ask = float(ticker["ask1Price"])
                last = float(ticker["lastPrice"])

                if self.last_atr > 0 and abs(last - proposal["entry"]) > self.last_atr * ENTRY_MAX_MOVE_ATR:
                    self.pending_proposal = None
                    return False, "Цена ушла слишком далеко. Нужен новый сигнал."

                instrument = await self.client.instrument(SYMBOL)
                tick = float(instrument.get("priceFilter", {}).get("tickSize", self.tick_size))
                maker_price = (
                    self._round_price(bid - tick, tick)
                    if proposal["side"] == "Buy"
                    else self._round_price(ask + tick, tick)
                )
                equity = await self._equity()
                stop = float(proposal["stop"])
                stop_distance = abs(maker_price - stop)
                if stop_distance <= 0:
                    return False, "Некорректное расстояние до SL после подтверждения."
                take = maker_price + stop_distance * TARGET_RR if proposal["side"] == "Buy" else maker_price - stop_distance * TARGET_RR
                qty = self._size_position(equity, maker_price, stop_distance)
                if qty < self.min_qty:
                    return False, "После повторной проверки размер позиции меньше минимального."

                self.pending_proposal = None

                if TRADING_MODE == "PAPER":
                    now = datetime.now(timezone.utc)
                    self.paper_position = {
                        "side": proposal["side"], "qty": qty, "entry": maker_price,
                        "stop": stop, "take": take,
                        "risk_usdt": abs(maker_price - stop) * qty,
                        "target_usdt": abs(take - maker_price) * qty,
                        "leverage": LEVERAGE, "opened_at": now.isoformat(),
                        "entry_type": "PAPER_MAKER",
                    }
                    self.trades_today += 1
                    self.last_trade_at = now
                    append_journal(self.state, "PAPER_OPEN_CONFIRMED",
                                   self.paper_position | {"proposal_id": proposal_id})
                    self._persist()
                    return True, f"PAPER: maker-вход {self._fmt(maker_price)}. Позиция создана."

                if TRADING_MODE == "LIVE" and not self.live_armed:
                    self.pending_proposal = proposal
                    return False, "LIVE заблокирован: сначала подтверди LIVE отдельной кнопкой."
                await self.client.set_leverage(SYMBOL, LEVERAGE)
                order_link = f"ai-{proposal_id}"
                result = await self.client.create_postonly_order(
                    SYMBOL, proposal["side"], self._fmt(qty), self._fmt(maker_price),
                    self._fmt(stop), self._fmt(take), order_link
                )
                self.pending_order = {
                    "order_id": result.get("orderId"),
                    "order_link_id": order_link,
                    "proposal": {**proposal, "entry": maker_price, "stop": stop, "take": take, "qty": qty, "rr": TARGET_RR},
                    "created_at": time.time(),
                }
                self.last_trade_at = datetime.now(timezone.utc)
                self._persist()
                return True, f"{TRADING_MODE}: PostOnly заявка размещена по {self._fmt(maker_price)}."

            except Exception as exc:
                self.last_error = str(exc)
                return False, f"Вход не размещён: {exc}"

    async def reject_proposal(self, proposal_id):
        if self.pending_proposal and self.pending_proposal.get("id") == proposal_id:
            self.pending_proposal = None
            return True
        return False

    async def close_position(self):
        """Manually close the current position. Never opens a new order."""
        async with self._lock:
            try:
                if TRADING_MODE == "PAPER":
                    position = self.paper_position
                    if not position:
                        return False, "Открытой позиции нет."
                    ticker = await self.client.ticker(SYMBOL)
                    exit_price = float(ticker.get("lastPrice", 0) or 0)
                    if exit_price <= 0:
                        return False, "Не удалось получить текущую цену."
                    side = position["side"]
                    direction = 1 if side == "Buy" else -1
                    pnl = (exit_price - float(position["entry"])) * float(position["qty"]) * direction
                    self.realized_today += pnl
                    self.paper_capital = max(0.0, self.paper_capital + pnl)
                    append_journal(self.state, "PAPER_CLOSE_MANUAL", {
                        **position, "exit": exit_price, "pnl": pnl, "result": "MANUAL",
                    })
                    self.paper_position = None
                    self._persist()
                    await self._emit_event(
                        f"{'🟢' if pnl >= 0 else '🔴'} PAPER: позиция закрыта вручную.\n"
                        f"{SYMBOL}\nВыход: {exit_price:.4f}\nP&L: {pnl:+.4f} USDT"
                    )
                    return True, f"PAPER: позиция закрыта по {self._fmt(exit_price)}. P&L {pnl:+.4f} USDT"

                position = await self.client.position(SYMBOL)
                if not position:
                    return False, "Открытой позиции нет."
                side = position.get("side")
                qty = float(position.get("size", 0) or 0)
                if side not in {"Buy", "Sell"} or qty <= 0:
                    return False, "Не удалось определить размер позиции."
                result = await self.client.close_market(SYMBOL, {"side": side, "size": self._fmt(qty)})
                self.pending_order = None
                self.exchange_trade = None
                self._persist()
                await self._emit_event(
                    f"🟠 {TRADING_MODE}: отправлено закрытие позиции.\n{SYMBOL}\nРазмер: {qty:g}"
                )
                return True, f"{TRADING_MODE}: команда закрытия отправлена."
            except Exception as exc:
                self.last_error = str(exc)
                return False, f"Закрытие не выполнено: {exc}"

    async def _monitor_pending_order(self):
        if not self.pending_order:
            return
        order = self.pending_order
        try:
            if time.time() - order["created_at"] > PROPOSAL_EXPIRY_SECONDS:
                await self.client.cancel_order(
                    SYMBOL, order_id=order.get("order_id"),
                    order_link_id=order.get("order_link_id")
                )
                self.pending_order = None
                self._persist()
                return
            status = await self.client.order(
                SYMBOL, order_id=order.get("order_id"),
                order_link_id=order.get("order_link_id")
            )
            if not status:
                return
            state = str(status.get("orderStatus", ""))
            if state == "Filled":
                proposal = order.get("proposal", {})
                avg_price = float(status.get("avgPrice", 0) or proposal.get("entry", 0) or 0)
                filled_qty = float(status.get("cumExecQty", 0) or proposal.get("qty", 0) or 0)
                self.exchange_trade = {
                    "side": proposal.get("side"),
                    "qty": filled_qty,
                    "entry": avg_price,
                    "stop": float(proposal.get("stop", 0) or 0),
                    "take": float(proposal.get("take", 0) or 0),
                    "opened_at_ms": int(time.time() * 1000),
                    "order_id": order.get("order_id"),
                }
                append_journal(self.state, f"{TRADING_MODE}_ORDER_FILLED", status | {"entry": avg_price, "qty": filled_qty})
                self.trades_today += 1
                self.pending_order = None
                self._persist()
                await self._emit_event(
                    f"🟡 {TRADING_MODE}: позиция открыта.\n"
                    f"{SYMBOL} {proposal.get('side')}\n"
                    f"Вход: {avg_price:.4f}\nSL: {float(proposal.get('stop', 0) or 0):.4f}\nTP: {float(proposal.get('take', 0) or 0):.4f}"
                )
            elif state == "PartiallyFilled":
                append_journal(self.state, f"{TRADING_MODE}_ORDER_PARTIAL", status)
                self._persist()
            elif state in {"Cancelled", "Rejected", "Deactivated"}:
                self.pending_order = None
                self._persist()
        except Exception as exc:
            self.last_error = str(exc)

    async def paper_monitor(self, price, ticker=None):
        position = self.paper_position
        if not position:
            return
        side = position["side"]
        stop = float(position["stop"])
        take = float(position["take"])
        hit_stop = (side == "Buy" and price <= stop) or (side == "Sell" and price >= stop)
        hit_take = (side == "Buy" and price >= take) or (side == "Sell" and price <= take)
        if not hit_stop and not hit_take:
            return
        result = "TP" if hit_take and not hit_stop else "SL"
        exit_price = take if result == "TP" else stop
        direction = 1 if side == "Buy" else -1
        pnl = (exit_price - float(position["entry"])) * float(position["qty"]) * direction
        self.realized_today += pnl
        self.paper_capital = max(0.0, self.paper_capital + pnl)
        append_journal(self.state, "PAPER_CLOSE", {
            **position, "exit": exit_price, "pnl": pnl, "result": result,
        })
        self.paper_position = None
        self._persist()
        await self._emit_event(
            f"{'🟢' if pnl >= 0 else '🔴'} PAPER: позиция закрыта.\n"
            f"{SYMBOL}\nРезультат: {result}\nВыход: {exit_price:.4f}\n"
            f"P&L: {pnl:+.4f} USDT\nКапитал: {self.paper_capital:.4f} USDT"
        )

    async def status(self):
        balance = 0.0
        position = None
        try:
            balance = await self._equity()
            if balance and TRADING_MODE != "PAPER":
                position = await self.client.position(SYMBOL)
        except Exception as exc:
            self.last_error = str(exc)
        return {
            "symbol": SYMBOL, "mode": TRADING_MODE, "dry_run": TRADING_MODE == "PAPER",
            "trading_enabled": TRADING_ENABLED, "capital": balance, "live_armed": self.live_armed,
            "position": position or self.paper_position,
            "trades_today": self.trades_today,
            "realized_today": self.realized_today,
            "daily_limit": self._daily_limit(),
            "risk_pct": RISK_PER_TRADE_PCT, "leverage": LEVERAGE,
            "rr": TARGET_RR, "risk_filter": MAX_AI_RISK_SCORE,
            "pending_proposal": self.pending_proposal,
            "pending_order": self.pending_order,
            "trade_capital": TRADE_CAPITAL_USDT,
            "last_cycle": self.last_cycle.isoformat() if self.last_cycle else None,
            "last_error": self.last_error,
        }


    def set_mode(self, mode: str):
        mode = mode.upper().strip()
        if mode not in {"PAPER", "DEMO", "LIVE"}:
            raise ValueError("mode must be PAPER, DEMO or LIVE")
        self.live_armed = False
        self.pending_proposal = None
        return mode

    def arm_live(self, confirmed: bool):
        self.live_armed = bool(confirmed) and TRADING_MODE == "LIVE"
        return self.live_armed

    def set_paper_capital(self, amount: float):
        if amount <= 0:
            raise ValueError("paper capital must be > 0")
        if self.paper_position or self.pending_order:
            raise ValueError("Нельзя менять капитал при активной позиции или заявке")
        self.paper_capital = float(amount)
        if TRADING_MODE == "PAPER":
            self.starting_equity = self.paper_capital
            self.realized_today = 0.0
        self._persist()

    async def run(self):
        self.running = True
        await self.start()
        while self.running:
            try:
                await self.cycle()
                if self.paper_position and self.last_price > 0:
                    await self.paper_monitor(self.last_price)
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Engine loop error")
            await asyncio.sleep(POLL_SECONDS)
