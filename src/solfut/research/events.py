"""Event-study (PLAN M2.5) — chứng minh edge trong vi cấu trúc TRƯỚC khi backtest.

Phép đo: forward-return có điều kiện vs baseline vô điều kiện, moving-block bootstrap
(crypto fat-tailed, không iid), decay curve theo horizon, MFE/MAE.
Tiêu chí kill pre-registered (mặc định theo PLAN): excess ≥ 0.05% @+1h, t ≥ 2 trên TRAIN,
giữ hướng trên VAL.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZONS = {"+5m": 1, "+15m": 3, "+1h": 12, "+4h": 48}


def forward_returns(close: pd.Series, horizon_bars: int) -> pd.Series:
    """Label: return từ close[t] đến close[t+h] (chỉ dùng làm label đo lường)."""
    return close.shift(-horizon_bars) / close - 1


def mfe_mae(close: pd.Series, high: pd.Series, low: pd.Series,
            horizon_bars: int = 48) -> pd.DataFrame:
    """MFE/MAE trong h bar sau event (theo % giá)."""
    fwd_high = pd.Series([high.iloc[i + 1:i + 1 + horizon_bars].max() if i + 1 + horizon_bars <= len(high) else np.nan
                          for i in range(len(high))], index=close.index)
    fwd_low = pd.Series([low.iloc[i + 1:i + 1 + horizon_bars].min() if i + 1 + horizon_bars <= len(low) else np.nan
                         for i in range(len(low))], index=close.index)
    return pd.DataFrame({
        "mfe": fwd_high / close - 1,
        "mae": fwd_low / close - 1,
    })


def _block_bootstrap_mean_ci(x: np.ndarray, block: int = 48, n_boot: int = 1000,
                             seed: int = 42) -> tuple[float, float, float]:
    """Mean + CI 95% qua moving-block bootstrap (x có thể chứa NaN — bỏ)."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 100:
        return np.nan, np.nan, np.nan
    n_blocks = int(np.ceil(n / block))
    starts_max = n - block
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, starts_max, n_blocks)
        sample = np.concatenate([x[s:s + block] for s in starts])[:n]
        means[b] = sample.mean()
    return float(x.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _t_stat(x: np.ndarray, baseline_mean: float) -> float:
    x = x[~np.isnan(x)]
    if len(x) < 100:
        return np.nan
    se = x.std(ddof=1) / np.sqrt(len(x))
    return float((x.mean() - baseline_mean) / se) if se > 0 else np.nan


@dataclass
class EventResult:
    hid: str
    n_events: int
    excess_by_horizon: dict      # {"+1h": mean_event − mean_all}
    t_by_horizon: dict
    ci_event_by_horizon: dict    # CI của mean fwd-return CỦA EVENT (bootstrap)
    mfe_mae_stats: dict
    excess_is_mean: bool         # True


def run_event_study(df: pd.DataFrame, event_mask: pd.Series, hid: str,
                    horizons: dict | None = None, block: int = 48, sign: int = 1) -> EventResult:
    """df cần: close, high, low (index UTC). event_mask: bool tại bar event.
    sign=+1 đo drift long; sign=−1 đo drift short (MFE/MAE đảo tương ứng)."""
    horizons = horizons or HORIZONS
    ev_idx = df.index[event_mask.fillna(False)]
    res_h, t_h, ci_h = {}, {}, {}
    stats = {}
    for name, h in horizons.items():
        fwd = forward_returns(df["close"], h)
        base_mean = float((sign * fwd.dropna()).mean())
        ev = (sign * fwd).loc[ev_idx].dropna().values
        res_h[name] = float(np.nanmean(ev) - base_mean) if len(ev) else np.nan
        t_h[name] = _t_stat(ev, base_mean)
        m, lo, hi_ = _block_bootstrap_mean_ci(ev, block=block)
        ci_h[name] = {"mean": m, "lo": lo, "hi": hi_}
        if name == "+1h":
            mm = mfe_mae(df["close"], df["high"], df["low"], h)
            ev_mfe = mm.loc[ev_idx, "mfe"].dropna()
            ev_mae = mm.loc[ev_idx, "mae"].dropna()
            if sign == -1:
                ev_mfe, ev_mae = -ev_mae, -ev_mfe
            stats = {
                "mfe_median": float(ev_mfe.median()) if len(ev_mfe) else np.nan,
                "mfe_q75": float(ev_mfe.quantile(0.75)) if len(ev_mfe) else np.nan,
                "mae_median": float(ev_mae.median()) if len(ev_mae) else np.nan,
                "mae_q25": float(ev_mae.quantile(0.25)) if len(ev_mae) else np.nan,
            }
    return EventResult(hid=hid, n_events=int(event_mask.sum()),
                       excess_by_horizon=res_h, t_by_horizon=t_h,
                       ci_event_by_horizon=ci_h, mfe_mae_stats=stats, excess_is_mean=True)


def judge(res: EventResult, split: str, criteria: dict) -> str:
    """Áp tiêu chí pre-registered. TRAIN: excess@+1h ≥ min và t ≥ 2 và CI không chứa 0.
    VAL: cùng hướng (dấu) excess@+1h. Split khác: không chấm (tránh peeking)."""
    horizon = criteria.get("horizon", "+1h")
    ex = res.excess_by_horizon.get(horizon, np.nan)
    if split == "TRAIN":
        ok_ex = ex == ex and ex >= criteria.get("excess_min_pct", 0.0005)
        ok_t = res.t_by_horizon.get(horizon, np.nan) >= criteria.get("t_min", 2.0)
        ci = res.ci_event_by_horizon.get(horizon, {})
        ok_ci = ci.get("lo", np.nan) is not np.nan and ci.get("lo") is not None and ci["lo"] > 0
        return "pass" if (ok_ex and ok_t and ok_ci) else "kill"
    if split == "VAL":
        return "keep_direction" if (ex == ex and ex > 0) else "val_negative"
    return "not_scored"
