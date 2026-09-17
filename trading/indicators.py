from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df.close.shift(1)
    tr = pd.concat([(df.high - df.low), (df.high - prev).abs(), (df.low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(s, 12) - ema(s, 26)
    signal = ema(line, 9)
    return line, signal, line - signal


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df.high.diff()
    down = -df.low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    a = atr(df, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / a
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = ema(out.close, 20)
    out["ema50"] = ema(out.close, 50)
    out["ema200"] = ema(out.close, 200)
    out["rsi"] = rsi(out.close)
    out["atr"] = atr(out)
    out["atr_pct"] = out.atr / out.close * 100
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out.close)
    out["adx"] = adx(out)
    out["vol_ma20"] = out.volume.rolling(20).mean()
    out["vol_ratio"] = out.volume / out.vol_ma20.replace(0, np.nan)
    out["high20"] = out.high.rolling(20).max().shift(1)
    out["low20"] = out.low.rolling(20).min().shift(1)
    out["bb_mid"] = out.close.rolling(20).mean()
    std = out.close.rolling(20).std()
    out["bb_upper"] = out.bb_mid + 2 * std
    out["bb_lower"] = out.bb_mid - 2 * std
    typical = (out.high + out.low + out.close) / 3
    # Bybit timestamps are numeric millisecond epochs. Cast explicitly before
    # pd.to_datetime so pandas does not interpret string timestamps as dates.
    start_ms = pd.to_numeric(out.start, errors="coerce")
    day = pd.to_datetime(start_ms, unit="ms", utc=True).dt.floor("D")
    pv = typical * out.volume
    out["vwap"] = pv.groupby(day).cumsum() / out.volume.groupby(day).cumsum().replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
