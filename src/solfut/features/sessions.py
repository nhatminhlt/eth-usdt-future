"""Activity filter thay session filter FX (PLAN M2): trade window 12:00–21:00 UTC,
skip 10–11 UTC, weekend toggle, blackout ±30' tin đỏ, ±5' quanh mốc funding (interval động).
"""
from __future__ import annotations

from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_news_calendar(path: Path | None = None) -> pd.DataFrame:
    path = path or (CONFIG_DIR / "news_calendar.csv")
    df = pd.read_csv(path)
    df["ts_utc"] = pd.to_datetime(df["date_utc"] + " " + df["time_utc"], utc=True)
    return df


def funding_marks(index: pd.DatetimeIndex, interval_hours: int = 8) -> pd.DatetimeIndex:
    """Các mốc funding trong phạm vi index — theo interval HIỆN HÀNH (luật 17)."""
    start = index.floor(f"{interval_hours}h")
    marks = pd.date_range(start[0], index[-1], freq=f"{interval_hours}h", tz=index.tz)
    return marks


def activity_mask(
    index: pd.DatetimeIndex,
    window_start: str = "12:00",
    window_end: str = "21:00",
    skip_hours: tuple[int, ...] = (10, 11),
    weekend_trading: bool = False,
    news: pd.DataFrame | None = None,
    news_blackout_min: int = 30,
    funding_interval_hours: int | None = 8,
    funding_blackout_min: int = 5,
) -> np.ndarray:
    """True = được phép MỞ vị thế tại bar t (nến t vừa đóng)."""
    allowed = np.ones(len(index), dtype=bool)
    h = index.hour
    m = index.minute
    minutes = h * 60 + m
    w0 = int(window_start[:2]) * 60 + int(window_start[3:])
    w1 = int(window_end[:2]) * 60 + int(window_end[3:])
    allowed &= (minutes >= w0) & (minutes < w1)
    for s in skip_hours:
        allowed &= h != s
    if not weekend_trading:
        allowed &= ~np.isin(index.dayofweek, [5, 6])

    if news is not None and len(news):
        ts = index.values
        t0 = news["ts_utc"].values - np.timedelta64(news_blackout_min, "m")
        t1 = news["ts_utc"].values + np.timedelta64(news_blackout_min, "m")
        blocked = np.zeros(len(index), dtype=bool)
        # vectorized: searchsorted mỗi mốc
        for a, b in zip(t0, t1):
            i0, i1 = np.searchsorted(ts, a), np.searchsorted(ts, b)
            if i1 > i0:
                blocked[i0:i1] = True
        allowed &= ~blocked

    if funding_interval_hours:
        marks = funding_marks(index, funding_interval_hours)
        ts = index.values
        blocked = np.zeros(len(index), dtype=bool)
        half = np.timedelta64(funding_blackout_min, "m")
        for f in marks.values:
            a, b = f - half, f + half
            i0, i1 = np.searchsorted(ts, a), np.searchsorted(ts, b)
            if i1 > i0:
                blocked[i0:i1] = True
        allowed &= ~blocked
    return allowed
