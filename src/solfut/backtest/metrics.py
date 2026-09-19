"""Metrics (PLAN M4 metrics.py) — expectancy/PF/SQN/maxDD trên $50, phân rã gross/cost/net,
bootstrap CI (moving-block — R trade fat-tailed, không iid), attribution theo regime, gate check.
Gate số đọc từ settings.gates — không hardcode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from solfut.config import settings


def compute_metrics(trades: pd.DataFrame, equity_start: float | None = None) -> dict:
    if equity_start is None:
        equity_start = settings()["risk"]["equity_start"]
    if trades is None or len(trades) == 0:
        return {"n_trades": 0}
    r = trades["r_net"].to_numpy(float)
    eq = equity_start + trades["net_pnl"].cumsum().to_numpy(float)
    peak = np.maximum.accumulate(np.concatenate([[equity_start], eq]))[1:]
    dd_pct = (peak - eq) / peak * 100
    gross_pos = trades.loc[trades["gross_pnl"] > 0, "gross_pnl"].sum()
    gross_neg = trades.loc[trades["gross_pnl"] <= 0, "gross_pnl"].sum()
    span_days = max((trades["exit_time"].max() - trades["exit_time"].min()).days, 1)
    m = {
        "n_trades": int(len(trades)),
        "win_rate": float((trades["net_pnl"] > 0).mean()),
        "expectancy_r": float(r.mean()),
        "gross_expectancy_r": float(trades["r_gross"].mean()),
        "cost_r": float((trades["cost_total"] / trades["risk_usdt"]).mean()),
        "profit_factor_gross": float(gross_pos / abs(gross_neg)) if gross_neg != 0 else float("inf"),
        "profit_factor_net": float(trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum()
                                   / abs(trades.loc[trades["net_pnl"] <= 0, "net_pnl"].sum()))
        if (trades["net_pnl"] <= 0).any() else float("inf"),
        "sqn_r": float(np.sqrt(len(r)) * r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else float("nan"),
        "max_dd_pct": float(dd_pct.max()),
        "trades_per_year": float(len(trades) / (span_days / 365.25)),
        "avg_bars_held": float(trades["bars_held"].mean()),
        "equity_end": float(eq[-1]),
        "exit_reasons": trades["exit_reason"].value_counts().to_dict(),
    }
    lo, hi = bootstrap_expectancy_ci(r)
    m["expectancy_ci95"] = [lo, hi]
    return m


def bootstrap_expectancy_ci(r: np.ndarray, block: int = 20, n_boot: int = 2000,
                            seed: int = 42) -> tuple[float, float]:
    """CI 95% expectancy qua moving-block bootstrap trên chuỗi R theo thời gian."""
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 100:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n - block, n_blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        means[b] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def regime_attribution(trades: pd.DataFrame, sol_d1_regime: pd.Series,
                       btc_d1_trend: pd.Series | None = None) -> pd.DataFrame:
    """Expectancy theo regime SOL D1 (attribution — không gate). Join theo NGÀY entry UTC."""
    day = trades["entry_time"].dt.floor("D")
    reg = day.map(sol_d1_regime).fillna("unknown")
    out = trades.assign(_reg=reg).groupby("_reg").agg(
        n=("r_net", "size"), expectancy_r=("r_net", "mean"),
        win_rate=("net_pnl", lambda x: float((x > 0).mean())))
    if btc_d1_trend is not None:
        bt = day.map(btc_d1_trend).fillna("unknown")
        out2 = trades.assign(_bt=bt).groupby("_bt").agg(
            n=("r_net", "size"), expectancy_r=("r_net", "mean"))
        out = pd.concat([out, out2], axis=0, keys=["sol_regime", "btc_trend"])
    return out


def gates_check(m: dict) -> dict:
    """Đối chiếu metrics với cổng settings.gates — trả {gate: {ok, value, min}}."""
    g = settings()["gates"]
    res = {}
    if m.get("n_trades", 0) == 0:
        return {"no_trades": {"ok": False}}
    lo, _ = m.get("expectancy_ci95", (float("nan"), float("nan")))
    res["gross_positive"] = {"ok": m["gross_expectancy_r"] > 0, "value": round(m["gross_expectancy_r"], 4)}
    res["net_expectancy"] = {"ok": m["expectancy_r"] >= g["expectancy_min_r"],
                             "value": round(m["expectancy_r"], 4), "min": g["expectancy_min_r"]}
    res["ci_excludes_zero"] = {"ok": lo == lo and lo > 0, "value": None if lo != lo else round(lo, 4)}
    res["sqn"] = {"ok": m["sqn_r"] >= g["sqn_min"], "value": round(m["sqn_r"], 2), "min": g["sqn_min"]}
    res["pf_net"] = {"ok": m["profit_factor_net"] >= g["pf_min"], "value": round(m["profit_factor_net"], 3), "min": g["pf_min"]}
    res["n_trades"] = {"ok": m["n_trades"] >= g["trades_per_segment_min"], "value": m["n_trades"], "min": g["trades_per_segment_min"]}
    res["max_dd"] = {"ok": m["max_dd_pct"] <= g["max_dd_pct"], "value": round(m["max_dd_pct"], 1), "max": g["max_dd_pct"]}
    res["trades_per_year"] = {"ok": m["trades_per_year"] >= g["min_trades_per_year"],
                              "value": round(m["trades_per_year"], 1), "min": g["min_trades_per_year"]}
    res["ALL_PASS"] = {"ok": all(v["ok"] for v in res.values())}
    return res
