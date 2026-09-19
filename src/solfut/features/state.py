"""Trạng thái thị trường (PLAN M2): always-in (Brooks), tight-TR, barbwire.

Machine subset — ghi rõ định nghĩa; ADR20 truyền vào từ D1 (không tính nội bộ để tránh
nhầm timeframe). Mọi hàm causal.
"""
from __future__ import annotations

import pandas as pd


def always_in(df: pd.DataFrame) -> pd.DataFrame:
    """Proxy máy của always-in (Brooks): close vs EMA20 + hướng slope EMA20 (5 bar).
    always_in_long = close > ema20 và slope dương (qua màu diff 5 bar của ema20)."""
    out = df.copy()
    e = out["ema20"]
    slope = e.diff(5)
    out["always_in_long"] = (out["close"] > e) & (slope > 0)
    out["always_in_short"] = (out["close"] < e) & (slope < 0)
    return out


def tight_tr(df: pd.DataFrame, adr20: pd.Series, n_bars: int = 20, frac: float = 0.30) -> pd.Series:
    """Tight trading range: range (maxH−minL) của n bar gần nhất ≤ frac × ADR20 (giá)."""
    hi = df["high"].rolling(n_bars).max()
    lo = df["low"].rolling(n_bars).min()
    adr_per_bar = adr20.reindex(df.index, method="ffill") if isinstance(adr20.index, pd.DatetimeIndex) else adr20
    return (hi - lo) <= frac * adr_per_bar


def barbwire(df: pd.DataFrame, adr20: pd.Series, n_bars: int = 8, frac: float = 0.25) -> pd.Series:
    """Barbwire (Elder): n bar chồng lấn, net change nhỏ, đè sát EMA20."""
    hi = df["high"].rolling(n_bars).max()
    lo = df["low"].rolling(n_bars).min()
    net = (df["close"] - df["close"].shift(n_bars)).abs()
    adr_per_bar = adr20.reindex(df.index, method="ffill") if isinstance(adr20.index, pd.DatetimeIndex) else adr20
    near_ema = (df["close"] - df["ema20"]).abs() <= 0.5 * adr_per_bar * frac * 4  # ~0.5×ADR20/5 (thô, grid kiểm chứng)
    return ((hi - lo) <= frac * adr_per_bar * 8) & (net <= frac * adr_per_bar) & near_ema


def add_state(df: pd.DataFrame, adr20_daily: pd.Series) -> pd.DataFrame:
    out = always_in(df)
    out["tight_tr"] = tight_tr(out, adr20_daily)
    out["barbwire"] = barbwire(out, adr20_daily)
    return out
