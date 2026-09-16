from __future__ import annotations

import pandas as pd


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return (100 - (100 / (1 + rs))).fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df.close.shift(1)
    tr = pd.concat([
        df.high - df.low,
        (df.high - prev).abs(),
        (df.low - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = ema(s, 12)
    slow = ema(s, 26)
    line = fast - slow
    signal = ema(line, 9)
    return line, signal, line - signal


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = ema(out.close, 20)
    out["ema50"] = ema(out.close, 50)
    out["ema200"] = ema(out.close, 200)
    out["rsi"] = rsi(out.close)
    out["atr"] = atr(out)
    out["atr_pct"] = out.atr / out.close * 100
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out.close)
    out["vol_ma20"] = out.volume.rolling(20).mean()
    out["vol_ratio"] = out.volume / out.vol_ma20
    out["high20"] = out.high.rolling(20).max()
    out["low20"] = out.low.rolling(20).min()
    return out.dropna().reset_index(drop=True)
