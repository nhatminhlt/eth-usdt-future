"""Context (PLAN M2): BTC D1 trend filter + regime attribution bull/bear/chop cho SOL.

Quy tắc an toàn PLAN: BTC-filter chỉ là ỨNG VIÊN qua ablation (TRAIN chọn, VAL xác nhận);
regime CHỈ dùng để attribution kết quả, không gate tín hiệu.
"""
from __future__ import annotations

import pandas as pd

from .indicators import adx, ema


def btc_d1_trend(btc_d1: pd.DataFrame) -> pd.DataFrame:
    """Trend BTC D1: EMA20 slope (10 ngày) + ADX14. up/down/flat."""
    out = btc_d1.copy()
    e = ema(out["close"], 20)
    slope = e.diff(10)
    a = adx(out, 14)
    out["btc_trend"] = pd.Series(
        pd.NA, index=out.index, dtype="object")
    out.loc[(slope > 0) & (a >= 20), "btc_trend"] = "up"
    out.loc[(slope < 0) & (a >= 20), "btc_trend"] = "down"
    out["btc_trend"] = out["btc_trend"].fillna("flat")
    return out


def sol_regime(sol_d1: pd.DataFrame, sma: int = 200, adx_flat: float = 20) -> pd.DataFrame:
    """Regime attribution SOL D1: bull (close > SMA200 & slope dương),
    bear (đối ứng), chop (ADX14 < 20). CHỈ dùng cho attribution."""
    out = sol_d1.copy()
    sma_v = out["close"].rolling(sma).mean()
    slope = sma_v.diff(10)
    a = adx(out, 14)
    out["regime"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out.loc[(out["close"] > sma_v) & (slope > 0), "regime"] = "bull"
    out.loc[(out["close"] < sma_v) & (slope < 0), "regime"] = "bear"
    out.loc[a < adx_flat, "regime"] = "chop"
    out["regime"] = out["regime"].fillna("transitional")
    return out
