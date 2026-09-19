"""Random-entry baseline (PLAN M2.5/M5 — Tharp): expectancy(strategy) − expectancy(random)
cùng luật thoát + cùng chi phí trên cùng dữ liệu. Không vượt random → mọi "edge" chỉ là
hình dáng của luật thoát → kill.

Random entry: lấy mẫu n lệnh từ các nến ĐƯỢC PHÉP bởi activity mask, giữ single-position
(không chồng lấn — chọn greedy từ mẫu xáo trộn), SL/TP/holding PHẨM CHẤT giống strategy
cùng scenario/bound/cost — chạy qua CÙNG engine run_backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from solfut.backtest.costs import CostModel
from solfut.backtest.engine import run_backtest


def random_baseline(ohlc: pd.DataFrame, n_trades_target: int, cost: CostModel,
                    scenario: str, bound: str, sl_pct: float, tp_pct: float,
                    holding_bars: int, activity: np.ndarray | None = None,
                    k_seeds: int = 30, seed: int = 42,
                    funding=None, patience_bars: int = 12) -> dict:
    idx = ohlc.index
    allowed = np.flatnonzero(activity) if activity is not None else np.arange(len(idx))
    if len(allowed) < n_trades_target * 2:
        return {"error": "không đủ nến allowed"}

    rng = np.random.default_rng(seed)
    exps, ns = [], []
    for k in range(k_seeds):
        # xáo trộn nến allowed → greedy chọn non-overlap theo holding_bars
        cand = rng.permutation(allowed)
        chosen: list[int] = []
        last_end = -1
        limit = n_trades_target * 5        # chống vòng lặp dài
        for pos_i, bar in enumerate(cand):
            if len(chosen) >= n_trades_target or pos_i > limit:
                break
            if bar > last_end:
                chosen.append(bar)
                last_end = bar + holding_bars
        if not chosen:
            continue
        chosen.sort()
        sig = pd.DataFrame({
            "entry_time": idx[chosen], "sid": "random", "direction": 1,
            "entry_price": ohlc["close"].to_numpy(float)[chosen],
            "sl_pct": sl_pct, "tp_pct": tp_pct, "holding_bars": holding_bars,
        })
        res = run_backtest(ohlc, sig, cost, scenario=scenario, bound=bound,
                           activity=activity, patience_bars=patience_bars, funding=funding)
        if len(res.trades):
            exps.append(float(res.trades["r_net"].mean()))
            ns.append(len(res.trades))
    if not exps:
        return {"error": "random baseline không sinh được lệnh"}
    exps = np.array(exps)
    return {
        "k_seeds": len(exps),
        "n_trades_mean": float(np.mean(ns)),
        "random_expectancy_mean_r": float(exps.mean()),
        "random_expectancy_std_r": float(exps.std(ddof=1)),
        "random_expectancy_p95": float(np.percentile(exps, 95)),
    }


def edge_vs_random(strategy_expectancy_r: float, baseline: dict) -> dict:
    """Edge = strategy − random_mean; p-value xấp xỉ = tần suất random ≥ strategy."""
    if "error" in baseline:
        return baseline
    return {
        "edge_r": float(strategy_expectancy_r - baseline["random_expectancy_mean_r"]),
        "random_p95": baseline["random_expectancy_p95"],
        "beats_random_p95": bool(strategy_expectancy_r > baseline["random_expectancy_p95"]),
    }
