"""Pattern price-action — subset máy móc theo định nghĩa sách (PLAN: rating ≤ 3).

Tất cả boolean Series đánh giá TẠI bar t chỉ dùng bar ≤ t (no lookahead).
Định nghĩa machine subset (ghi rõ để có gì đối chiếu sách):
- inside_bar:  high ≤ prev_high và low ≥ prev_low
- outside_bar: high > prev_high và low < prev_low
- ii:          2 inside bar liên tiếp (Volman)
- ioi:         inside → outside → inside (Volman)
- powerbar:    range ≥ 1.5×ATR14 và close ở 25% cực của range (theo chiều)
- doji:        body ≤ 0.1×range
- reversal_bull/bear: low thấp hơn prev_low (high cao hơn prev_high) nhưng đóng ngược chiều ở 1/3 cực
- kangaroo_bull/bear (Volman): wick ≥ 60% range, thân ở đầu đối diện, bar vượt ra ngoài range 3 bar trước
- big_shadow_bull/bear (Volman): bar xuyên dưới/ trên min/max 3 bar trước, range ≥ 1.2×ATR, đóng ở 25% cực
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _body(df):
    return (df["close"] - df["open"]).abs()


def _range(df):
    return df["high"] - df["low"]


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    ph, pl, po, pc = df["high"].shift(1), df["low"].shift(1), df["open"].shift(1), df["close"].shift(1)
    rng = _range(df)
    body = _body(df)
    atr = out["atr14"] if "atr14" in out else None
    mid = (df["high"] + df["low"]) / 2

    inside = (df["high"] <= ph) & (df["low"] >= pl)
    outside = (df["high"] > ph) & (df["low"] < pl)
    out["inside_bar"] = inside
    out["outside_bar"] = outside
    out["ii"] = inside & inside.shift(1, fill_value=False)

    # ioi: bar t inside, t−1 outside, t−2 inside
    out["ioi"] = inside & outside.shift(1, fill_value=False) & inside.shift(2, fill_value=False)

    # powerbar (cần atr14 — caller phải chạy add_indicators trước)
    if atr is not None:
        big = rng >= 1.5 * atr
        top_quarter = df["close"] >= df["high"] - 0.25 * rng
        bot_quarter = df["close"] <= df["low"] + 0.25 * rng
        out["powerbar_bull"] = big & top_quarter & (df["close"] > df["open"])
        out["powerbar_bear"] = big & bot_quarter & (df["close"] < df["open"])

    out["doji"] = (body <= 0.1 * rng.replace(0, np.nan)).fillna(False)

    # reversal bar (Brooks): xuyên cực trị prev rồi đóng ngược
    out["reversal_bull"] = (df["low"] < pl) & (df["close"] > pc) & (df["close"] >= df["high"] - rng / 3)
    out["reversal_bear"] = (df["high"] > ph) & (df["close"] < pc) & (df["close"] <= df["low"] + rng / 3)

    # kangaroo tail: wick dài, thân nhỏ ở đầu đối diện, vượt khỏi range 3 bar trước
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    rng3hi = df["high"].rolling(3).max().shift(1)
    rng3lo = df["low"].rolling(3).min().shift(1)
    if atr is not None:
        out["kangaroo_bull"] = (lower_wick >= 0.6 * rng) & (body <= 0.3 * rng) & (df["low"] < rng3lo)
        out["kangaroo_bear"] = (upper_wick >= 0.6 * rng) & (body <= 0.3 * rng) & (df["high"] > rng3hi)
        out["big_shadow_bull"] = (df["low"] < rng3lo) & (rng >= 1.2 * atr) & (df["close"] >= df["high"] - 0.25 * rng)
        out["big_shadow_bear"] = (df["high"] > rng3hi) & (rng >= 1.2 * atr) & (df["close"] <= df["low"] + 0.25 * rng)
    return out
