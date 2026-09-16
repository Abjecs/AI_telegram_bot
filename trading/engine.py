from __future__ import annotations
import asyncio, logging, math
from datetime import datetime, timezone, date
import pandas as pd
from config import *
from trading.ai import confirm_signal
from trading.bybit import BybitClient, BybitError
from trading.indicators import enrich
from trading.strategy import Signal, evaluate

logger=logging.getLogger(__name__)

class TradingEngine:
    def __init__(self):
        self.client=BybitClient(); self.running=False; self.last_signal=None; self.last_error=""
        self.trades_today=0; self.realized_today=0.0; self.last_cycle=None; self.last_trade_at=None
        self.last_candle=0; self.paper_position=None; self._lock=asyncio.Lock(); self.qty_step=.001; self.min_qty=.001
        self.day=date.today()

    async def start(self):
        self.running=True; await self.client.start()
        try:
            i=await self.client.instrument(SYMBOL); lot=i.get("lotSizeFilter",{})
            self.qty_step=float(lot.get("qtyStep",self.qty_step)); self.min_qty=float(lot.get("minOrderQty",self.min_qty))
        except Exception as e: logger.warning("Instrument load failed: %s",e)
        logger.info("Trading engine started symbol=%s dry_run=%s",SYMBOL,DRY_RUN)

    async def stop(self): self.running=False; await self.client.close()
    def _round_qty(self,q): return math.floor(q/self.qty_step)*self.qty_step if self.qty_step>0 else q
    async def _equity(self): return CAPITAL_USDT if CAPITAL_USDT>0 else await self.client.balance()
    def _reset_day(self):
        today=datetime.now(timezone.utc).date()
        if today!=self.day: self.day=today; self.trades_today=0; self.realized_today=0.0; self.last_trade_at=None
    def _cooldown(self):
        if not self.last_trade_at: return False
        return (datetime.now(timezone.utc)-self.last_trade_at).total_seconds()<COOLDOWN_MINUTES*60
    def _microstructure_ok(self,ticker,book):
        bid=float(ticker.get("bid1Price",0)); ask=float(ticker.get("ask1Price",0))
        if bid<=0 or ask<=0: return False
        mid=(bid+ask)/2; spread=(ask-bid)/mid*100
        if spread>MAX_SPREAD_PCT: return False
        bids=sum(float(x[1]) for x in book.get("b",[])[:10]); asks=sum(float(x[1]) for x in book.get("a",[])[:10])
        return bids+asks>0

    async def cycle(self):
        async with self._lock:
            self.last_cycle=datetime.now(timezone.utc); self._reset_day()
            if not TRADING_ENABLED or self.trades_today>=MAX_TRADES_PER_DAY or self.realized_today<=-MAX_DAILY_LOSS_USDT: return
            try:
                existing=None if DRY_RUN else await self.client.position(SYMBOL)
                if existing: return
                if self.paper_position: return
                if self._cooldown(): return
                k5,k15=await asyncio.gather(self.client.klines(SYMBOL,"5",250),self.client.klines(SYMBOL,"15",250))
                df5,df15=enrich(self._df(k5)),enrich(self._df(k15))
                candle=int(df5.iloc[-1].start)
                if candle==self.last_candle: return
                self.last_candle=candle
                a=df5.iloc[-1]
                if not (MIN_ATR_PCT<=float(a.atr_pct)<=MAX_ATR_PCT): return
                ticker,book=await asyncio.gather(self.client.ticker(SYMBOL),self.client.orderbook(SYMBOL,25))
                if not self._microstructure_ok(ticker,book): return
                signal=evaluate(df5,df15); self.last_signal=signal
                if not signal: return
                bids=sum(float(x[1]) for x in book.get("b",[])[:10]); asks=sum(float(x[1]) for x in book.get("a",[])[:10])
                imbalance=bids/(bids+asks) if bids+asks else .5
                if signal.side=="Buy" and imbalance<.42: return
                if signal.side=="Sell" and imbalance>.58: return
                rr=abs(signal.take-signal.entry)/max(abs(signal.entry-signal.stop),1e-9)
                if rr<1.2: return
                ai_ok,ai_reason=await confirm_signal({"symbol":SYMBOL,"side":signal.side,"score":signal.score,"entry":signal.entry,"stop":signal.stop,"take":signal.take,"rsi_5m":float(a.rsi),"adx_5m":float(a.adx),"atr_pct_5m":float(a.atr_pct),"volume_ratio":float(a.vol_ratio),"vwap":float(a.vwap),"orderbook_imbalance":imbalance,"spread_pct":abs(float(ticker["ask1Price"])-float(ticker["bid1Price"])) / float(ticker["lastPrice"])*100,"reward_risk":rr,"reason":signal.reason})
                if not ai_ok: logger.info("AI rejected/failed: %s",ai_reason); return
                equity=await self._equity()
                stop_distance=abs(signal.entry-signal.stop)
                risk=equity*RISK_PER_TRADE_PCT/100
                qty=self._round_qty(risk/stop_distance)
                max_notional=equity*MAX_POSITION_NOTIONAL_PCT/100*LEVERAGE
                qty=min(qty,self._round_qty(max_notional/signal.entry))
                if qty<self.min_qty: return
                self.last_trade_at=datetime.now(timezone.utc); self.trades_today+=1
                if DRY_RUN:
                    self.paper_position={"side":signal.side,"qty":qty,"entry":signal.entry,"stop":signal.stop,"take":signal.take,"opened_at":self.last_trade_at.isoformat()}
                    logger.info("PAPER %s qty=%s entry=%.2f SL=%.2f TP=%.2f AI=%s",signal.side,qty,signal.entry,signal.stop,signal.take,ai_reason)
                else:
                    await self.client.set_leverage(SYMBOL,LEVERAGE)
                    await self.client.create_market_order(SYMBOL,signal.side,self._fmt_qty(qty),self._fmt_price(signal.stop),self._fmt_price(signal.take))
                    logger.info("LIVE %s qty=%s entry=%.2f SL=%.2f TP=%.2f AI=%s",signal.side,qty,signal.entry,signal.stop,signal.take,ai_reason)
            except BybitError as e: self.last_error=str(e); logger.exception("Bybit cycle error")
            except Exception as e: self.last_error=str(e); logger.exception("Trading cycle error")

    async def paper_monitor(self, price:float):
        p=self.paper_position
        if not p: return
        hit=(p["side"]=="Buy" and (price<=p["stop"] or price>=p["take"])) or (p["side"]=="Sell" and (price>=p["stop"] or price<=p["take"]))
        if hit:
            exit_price=p["take"] if ((p["side"]=="Buy" and price>=p["take"]) or (p["side"]=="Sell" and price<=p["take"])) else p["stop"]
            pnl=(exit_price-p["entry"])*p["qty"]*(1 if p["side"]=="Buy" else -1)
            self.realized_today+=pnl; logger.info("PAPER CLOSE pnl=%.4f",pnl); self.paper_position=None

    @staticmethod
    def _df(rows):
        rows=list(reversed(rows)); return pd.DataFrame(rows,columns=["start","open","high","low","close","volume","turnover"]).astype({c:float for c in ["open","high","low","close","volume","turnover"]})
    @staticmethod
    def _fmt_qty(q): return f"{q:.8f}".rstrip("0").rstrip(".")
    @staticmethod
    def _fmt_price(p): return f"{p:.8f}".rstrip("0").rstrip(".")
    async def run(self):
        await self.start()
        try:
            while self.running:
                if DRY_RUN:
                    try: await self.paper_monitor(float((await self.client.ticker(SYMBOL))["lastPrice"]))
                    except Exception: pass
                await self.cycle(); await asyncio.sleep(POLL_SECONDS)
        finally: await self.stop()
    async def status(self):
        balance=position=None
        try:
            if TRADING_ENABLED and not DRY_RUN: balance,position=await asyncio.gather(self.client.balance(),self.client.position(SYMBOL))
        except Exception as e: self.last_error=str(e)
        return {"symbol":SYMBOL,"dry_run":DRY_RUN,"trading_enabled":TRADING_ENABLED,"capital":CAPITAL_USDT if CAPITAL_USDT>0 else balance,"position":position or self.paper_position,"trades_today":self.trades_today,"realized_today":self.realized_today,"last_cycle":self.last_cycle.isoformat() if self.last_cycle else None,"last_error":self.last_error}
