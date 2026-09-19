"""Magnet levels (PLAN M2): round numbers, pivots UTC 00:00, yesterday H/L, swing extremes.

Mọi cột là giá trị DÀNH CHO bar t nhưng chỉ tính từ dữ liệu < t (pivots/ngày trước, swing đã xác nhận).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_round_levels(df: pd.DataFrame, step_large: float = 10.0, step_small: float = 5.0,
                     price_col: str = "close") -> pd.DataFrame:
    """Round number gần nhất (trên/dưới) theo giá TRƯỚC bar hiện tại (shift 1)."""
    out = df.copy()
    price = out[price_col].shift(1)  # đóng bar trước → không lookahead
    step = pd.Series(np.where(price >= 50, step_large, step_small), index=out.index)
    below = (price / step).ffill()  # placeholder để giữ dtype
    below = np.floor(price / step) * step
    out["round_below"] = below
    out["round_above"] = below + step
    return out


def add_prev_day_levels(m5: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    """Yesterday H/L + pivot classic từ D1 NGÀY TRƯỚC — ghép theo ngày UTC của bar M5."""
    out = m5.copy()
    day = out.index.floor("1D")
    prev = d1.shift(1)  # giá trị của ngày trước
    out["prev_day_high"] = prev["high"].reindex(day).values
    out["prev_day_low"] = prev["low"].reindex(day).values
    p = (prev["high"] + prev["low"] + prev["close"]) / 3
    rng = prev["high"] - prev["low"]
    out["pivot"] = p.reindex(day).values
    out["pivot_r1"] = (2 * p - prev["low"]).reindex(day).values
    out["pivot_s1"] = (2 * p - prev["high"]).reindex(day).values
    out["pivot_r2"] = (p + rng).reindex(day).values
    out["pivot_s2"] = (p - rng).reindex(day).values
    return out


def add_swing_levels(df: pd.DataFrame, k: int = 12, max_levels: int = 20) -> pd.DataFrame:
    """Đỉnh/đáy swing đã XÁC NHẬN (cao/thấp hơn k bar mỗi phía) → mức gần nhất tính đến bar t.

    Swing tại bar i được xác nhận ở bar i+k → khi gán cho bar t, chỉ dùng swing có i+k ≤ t (shift k).
    """
    out = df.copy()
    hi, lo = df["high"].values, df["low"].values
    n = len(df)
    swing_high_idx = []
    swing_low_idx = []
    for i in range(k, n - k):
        if hi[i] == max(hi[i - k:i + k + 1]) and (hi[i - k:i + k + 1] == hi[i]).sum() == 1:
            swing_high_idx.append(i)
        if lo[i] == min(lo[i - k:i + k + 1]) and (lo[i - k:i + k + 1] == lo[i]).sum() == 1:
            swing_low_idx.append(i)

    def nearest_confirmed(idx_list, values, t, is_high):
        """Mức swing gần nhất với thời điểm xác nhận ≤ t."""
        best = np.nan
        for i in reversed(idx_list):
            if i + k <= t:  # đã xác nhận tại bar t
                best = values[i]
                break
        return best

    confirmed_h = np.full(n, np.nan)
    confirmed_l = np.full(n, np.nan)
    ptr_h = ptr_l = 0
    last_h = last_l = np.nan
    for t in range(n):
        while ptr_h < len(swing_high_idx) and swing_high_idx[ptr_h] + k <= t:
            last_h = hi[swing_high_idx[ptr_h]]
            ptr_h += 1
        while ptr_l < len(swing_low_idx) and swing_low_idx[ptr_l] + k <= t:
            last_l = lo[swing_low_idx[ptr_l]]
            ptr_l += 1
        confirmed_h[t] = last_h
        confirmed_l[t] = last_l
    out["swing_high_conf"] = confirmed_h
    out["swing_low_conf"] = confirmed_l
    return out


def magnet_distance_bars(df: pd.DataFrame, tp_dist: float) -> pd.Series:
    """Có magnet bất lợi trong khoảng tp_dist tới TP không (bool) — dùng filter S1."""
    adverse_high = (df["round_above"] - df["close"]) < tp_dist
    adverse_low = (df["close"] - df["round_below"]) < tp_dist
    return adverse_high | adverse_low
