from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

# Internal candidate gate only. Final entry, stop and take are chosen by AI.
MIN_CANDIDATE_SCORE = 6
MIN_CANDIDATE_ADX = 18.0


@dataclass
class Signal:
    side: str
    score: int
    entry: float
    stop: float
    take: float
    reason: str


def evaluate(df5: pd.DataFrame, df15: pd.DataFrame) -> Signal | None:
    a, b = df5.iloc[-1], df15.iloc[-1]
    long_points: list[str] = []
    short_points: list[str] = []
    long_score = short_score = 0
    if a.ema20 > a.ema50 > a.ema200: long_score += 2; long_points.append("5m EMA trend")
    if a.ema20 < a.ema50 < a.ema200: short_score += 2; short_points.append("5m EMA trend")
    if b.ema20 > b.ema50 > b.ema200: long_score += 2; long_points.append("15m EMA trend")
    if b.ema20 < b.ema50 < b.ema200: short_score += 2; short_points.append("15m EMA trend")
    if a.macd_hist > 0 and a.macd > a.macd_signal: long_score += 1; long_points.append("MACD")
    if a.macd_hist < 0 and a.macd < a.macd_signal: short_score += 1; short_points.append("MACD")
    if 52 <= a.rsi <= 68: long_score += 1; long_points.append("RSI")
    if 32 <= a.rsi <= 48: short_score += 1; short_points.append("RSI")
    if a.adx >= MIN_CANDIDATE_ADX:
        if a.close > a.ema20: long_score += 1; long_points.append("ADX/trend strength")
        if a.close < a.ema20: short_score += 1; short_points.append("ADX/trend strength")
    if a.vol_ratio >= 1.15:
        if a.close > a.open: long_score += 1; long_points.append("volume")
        if a.close < a.open: short_score += 1; short_points.append("volume")
    if a.close > a.high20: long_score += 2; long_points.append("20-bar breakout")
    if a.close < a.low20: short_score += 2; short_points.append("20-bar breakdown")
    if a.close > a.vwap: long_score += 1; long_points.append("VWAP")
    if a.close < a.vwap: short_score += 1; short_points.append("VWAP")
    if long_score < MIN_CANDIDATE_SCORE and short_score < MIN_CANDIDATE_SCORE:
        return None
    if long_score == short_score or abs(long_score - short_score) < 2:
        return None
    side = "Buy" if long_score > short_score else "Sell"
    score = max(long_score, short_score)
    entry = float(a.close)
    atr = max(float(a.atr), entry * 0.0005)
    stop = entry - atr if side == "Buy" else entry + atr
    take = entry + atr * 1.5 if side == "Buy" else entry - atr * 1.5
    reason = ", ".join(long_points if side == "Buy" else short_points)
    return Signal(side, score, entry, stop, take, reason)
