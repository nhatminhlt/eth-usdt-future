"""Splits dữ liệu theo PLAN M5 — mốc đóng băng, không bao giờ đổi sau khi chốt."""
from __future__ import annotations

import pandas as pd

SPLITS = {
    "TRAIN": ("2020-10-01", "2023-06-30"),
    "VAL": ("2023-07-01", "2024-06-30"),
    "OOS1": ("2024-07-01", "2025-08-31"),
    "FINAL_OOS2": ("2025-09-01", "2026-08-31"),  # đóng băng đến ngày quyết định go-live
}


def split_mask(index: pd.DatetimeIndex, split: str) -> pd.Series:
    start, end = pd.Timestamp(SPLITS[split][0], tz="UTC"), pd.Timestamp(SPLITS[split][1] + " 23:59", tz="UTC")
    return pd.Series((index >= start) & (index <= end), index=index)


def split_of(ts: pd.Timestamp) -> str:
    for name, (s, e) in SPLITS.items():
        if pd.Timestamp(s, tz="UTC") <= ts <= pd.Timestamp(e + " 23:59", tz="UTC"):
            return name
    return "OUT_OF_PLAN"
