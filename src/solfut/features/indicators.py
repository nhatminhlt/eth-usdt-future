"""Indicators — giữ nguyên bộ PLAN M2: EMA 13/20/25, MACD 12-26-9, ATR14, ADX14,
RSI14, BB(20,2), KC(20,1.5), momentum 12.

Tất cả hàm CAUSAL (chỉ dùng dữ liệu quá khứ) — test chống lookahead ở tests/.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TR_COLS = ("high", "low", "close")


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR: ewm alpha=1/period trên TR."""
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_s = true_range(df)
    atr_ = tr_s.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, period: int = 20, ndev: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_up": mid + ndev * sd, "bb_low": mid - ndev * sd})


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 1.5) -> pd.DataFrame:
    """Elder KC: EMA20 ± mult×ATR14."""
    mid = ema(df["close"], period)
    a = atr(df, 14)
    return pd.DataFrame({"kc_mid": mid, "kc_up": mid + mult * a, "kc_low": mid - mult * a})


def momentum(close: pd.Series, period: int = 12) -> pd.Series:
    return close.diff(period)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Bổ sung đầy đủ indicators vào df OHLCV (index UTC). Không đè cột có sẵn."""
    out = df.copy()
    for span in (13, 20, 25):
        out[f"ema{span}"] = ema(out["close"], span)
    out["atr14"] = atr(out, 14)
    out["rsi14"] = rsi(out["close"], 14)
    out["adx14"] = adx(out, 14)
    m = macd(out["close"])
    out[["macd", "macd_signal", "macd_hist"]] = m
    out["mom12"] = momentum(out["close"], 12)
    kc = keltner(out)
    out[["kc_mid", "kc_up", "kc_low"]] = kc
    bb = bollinger(out["close"])
    out[["bb_mid", "bb_up", "bb_low"]] = bb
    return out
