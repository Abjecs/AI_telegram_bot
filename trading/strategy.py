from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import ATR_STOP_MULTIPLIER, ATR_TP_MULTIPLIER, MIN_SIGNAL_SCORE


@dataclass
class Signal:
    side: str
    score: int
    entry: float
    stop: float
    take: float
    reason: str


def evaluate(df5: pd.DataFrame, df15: pd.DataFrame) -> Signal | None:
    a = df5.iloc[-1]
    b = df15.iloc[-1]
    prev = df5.iloc[-2]
    score_long = 0
    score_short = 0
    reasons: list[str] = []

    if a.ema20 > a.ema50 > a.ema200: score_long += 2
    if a.ema20 < a.ema50 < a.ema200: score_short += 2
    if b.ema20 > b.ema50: score_long += 2
    if b.ema20 < b.ema50: score_short += 2
    if a.macd_hist > 0: score_long += 1
    if a.macd_hist < 0: score_short += 1
    if 52 <= a.rsi <= 70: score_long += 1
    if 30 <= a.rsi <= 48: score_short += 1
    if a.vol_ratio >= 1.1:
        score_long += 1 if a.close > a.ema20 else 0
        score_short += 1 if a.close < a.ema20 else 0
    if a.close > prev.high20: score_long += 1
    if a.close < prev.low20: score_short += 1

    score = max(score_long, score_short)
    if score < MIN_SIGNAL_SCORE or score_long == score_short:
        return None

    side = "Buy" if score_long > score_short else "Sell"
    entry = float(a.close)
    atr = float(a.atr)
    if side == "Buy":
        stop = entry - atr * ATR_STOP_MULTIPLIER
        take = entry + atr * ATR_TP_MULTIPLIER
        reasons.append("bullish multi-timeframe structure")
    else:
        stop = entry + atr * ATR_STOP_MULTIPLIER
        take = entry - atr * ATR_TP_MULTIPLIER
        reasons.append("bearish multi-timeframe structure")
    return Signal(side, score, entry, stop, take, "; ".join(reasons))
