"""Resample M5 → H1/D1 + các mức tham chiếu: pivots UTC 00:00, round numbers, ADR20.

Crypto không có session close → pivots cắt UTC 00:00 là quy ước chuẩn thay 17:00 NY của FX.
"""
from __future__ import annotations

import pandas as pd

OHLCV = {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum", "quote_volume": "sum", "count": "sum",
         "taker_buy_volume": "sum", "taker_buy_quote_volume": "sum"}


def to_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.to_datetime(out["open_time"], unit="ms", utc=True)
    return out


def resample(m5: pd.DataFrame, freq: str) -> pd.DataFrame:
    """freq: '1h' hoặc '1D' — m5 có index UTC (to_utc_index)."""
    r = m5.resample(freq, label="left", closed="left").agg(OHLCV).dropna(subset=["open"])
    return r


def adr20(d1: pd.DataFrame) -> pd.Series:
    """ADR20 = trung bình động 20 phiên của range D1 (giá)."""
    return (d1["high"] - d1["low"]).rolling(20).mean()


def daily_pivots(d1: pd.DataFrame) -> pd.DataFrame:
    """Pivot classic từ nến D1 trước — áp dụng cho phiên UTC hiện tại."""
    p = (d1["high"] + d1["low"] + d1["close"]) / 3
    return pd.DataFrame({
        "pivot": p,
        "r1": 2 * p - d1["low"],
        "s1": 2 * p - d1["high"],
        "r2": p + (d1["high"] - d1["low"]),
        "s2": p - (d1["high"] - d1["low"]),
    })


def round_levels(price: float, step_small: float = 5.0, step_large: float = 10.0) -> dict:
    """Round number gần nhất: bước 10 USDT (siết 5 khi giá < 50 — PLAN mục 3)."""
    step = step_large if price >= 50 else step_small
    below = (price // step) * step
    return {"below": below, "above": below + step, "step": step}


def prev_day_levels(d1: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"prev_high": d1["high"].shift(1), "prev_low": d1["low"].shift(1)})
