"""Monte Carlo (PLAN M4 monte_carlo.py — mượn khung V1): shuffle thứ tự lệnh → phân phối
drawdown + losing streak; với vốn $50, drawdown biên quan trọng hơn point estimate.
Cost-shock đơn điệu: phí ×1.5 (sensitivity ±50% của plan, bao trùm hết-BNB +11%).
"""
from __future__ import annotations

import numpy as np

from solfut.config import settings


def mc_drawdown(r_net: np.ndarray, n_sims: int = 2000, seed: int = 42) -> dict:
    """Shuffle chuỗi R (giữ nguyên tập lệnh) → equity path risk 1%/lệnh (compound) → maxDD."""
    risk = settings()["risk"]["risk_per_trade_pct"] / 100
    r_net = r_net[~np.isnan(r_net)]
    if len(r_net) < 10:
        return {}
    rng = np.random.default_rng(seed)
    dds, streaks = np.empty(n_sims), np.empty(n_sims, dtype=int)
    for s in range(n_sims):
        x = rng.permutation(r_net)
        eq = np.ones(len(x) + 1)
        for i, r in enumerate(x):               # compound nhân: eq *= (1 + risk×r), floor 0 (ruin)
            eq[i + 1] = max(eq[i] * (1 + risk * r), 0.0)
        peak = np.maximum.accumulate(eq)
        dds[s] = ((peak - eq) / peak * 100).max()
        neg = x < 0
        # losing streak dài nhất
        streak, best = 0, 0
        for v in neg:
            streak = streak + 1 if v else 0
            best = max(best, streak)
        streaks[s] = best
    return {
        "max_dd_p50": float(np.percentile(dds, 50)),
        "max_dd_p95": float(np.percentile(dds, 95)),
        "max_dd_p99": float(np.percentile(dds, 99)),
        "losing_streak_p95": int(np.percentile(streaks, 95)),
        "n_sims": n_sims,
    }


def cost_shock_expectancy(trades_cost_r: np.ndarray, expectancy_r: float,
                          scale: float = 1.5) -> dict:
    """Expectancy sau khi chi phí phình ×scale (đơn điệu — mọi lệnh cùng bị đánh thuế thêm)."""
    cost_r = trades_cost_r[~np.isnan(trades_cost_r)]
    if len(cost_r) == 0:
        return {}
    extra = cost_r * (scale - 1)
    return {
        "scale": scale,
        "expectancy_r_shocked": float(expectancy_r - extra.mean()),
    }
