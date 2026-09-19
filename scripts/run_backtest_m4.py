"""M4 — Backtest A/B/C (hypothesis fades) trên TRAIN, 2 kịch bản execution × 2 bound same-bar,
kèm random-entry baseline, Monte Carlo drawdown, cost-shock ±50%, regime attribution.

Kịch bản: maker_base (entry post-only limit tại extreme event bar, fill trade-through)
          taker_worst (entry market taker tại close event bar).
Bound:    sl_first (bi quan — BÁO CÁO CHÍNH), tp_first (lạc quan — chỉ lãi ở đây = fragile, luật 8).

Chạy: .venv/Scripts/python.exe scripts/run_backtest_m4.py
Output: data/reports/m4_backtest_train.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.backtest.costs import FundingSchedule, load_cost_model
from solfut.backtest.engine import run_backtest
from solfut.backtest.metrics import compute_metrics, gates_check, regime_attribution
from solfut.backtest.monte_carlo import cost_shock_expectancy, mc_drawdown
from solfut.backtest.random_baseline import edge_vs_random, random_baseline
from solfut.data.downloader import DATA_DIR
from solfut.features.context import btc_d1_trend, sol_regime
from solfut.features.sessions import activity_mask, load_news_calendar
from solfut.research.splits import split_mask
from solfut.strategies.base import conflict_resolver
from solfut.strategies.hypothesis_fades import attach_sl_tp, generate_signals

SEGMENT = "TRAIN"
REPORT = DATA_DIR / "reports" / f"m4_backtest_{SEGMENT.lower()}.json"


def run_one(sid: str, seg_signals: pd.DataFrame, ohlc: pd.DataFrame, act: np.ndarray,
            funding: FundingSchedule, reg: pd.Series, bt: pd.Series) -> dict:
    """Chạy 1 chiến thuật: 2 kịch bản × 2 bound + sensitivity + random baseline + attribution."""
    out: dict = {"scenarios": {}}
    for scenario in ("maker_base", "taker_worst"):
        for bound in ("sl_first", "tp_first"):
            t0 = time.time()
            res = run_backtest(ohlc, seg_signals, load_cost_model(), scenario=scenario,
                               bound=bound, activity=act, funding=funding)
            m = compute_metrics(res.trades)
            g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
            entry = {"metrics": m, "gates": g, "engine_stats": res.stats,
                     "seconds": round(time.time() - t0, 1)}
            if bound == "sl_first" and len(res.trades):
                entry["regime_attribution"] = json.loads(
                    regime_attribution(res.trades, reg, bt).to_json())
            out["scenarios"].setdefault(scenario, {})[bound] = entry
            logger.info(f"{sid} {scenario} {bound}: n={m.get('n_trades', 0)} "
                        f"expR={m.get('expectancy_r', float('nan')):.3f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.3f} "
                        f"PF={m.get('profit_factor_net', float('nan'))} "
                        f"fill={res.stats.get('fill_rate_maker')}")

    # --- sensitivity: activity filter OFF (chính = sl_first, cả 2 kịch bản)
    for scenario in ("maker_base", "taker_worst"):
        res = run_backtest(ohlc, seg_signals, load_cost_model(), scenario=scenario,
                           bound="sl_first", activity=None, funding=funding)
        out["scenarios"][scenario]["sl_first_no_activity"] = {
            "metrics": compute_metrics(res.trades), "engine_stats": res.stats}

    # --- cost shock ±50% (phí phình 1.5×) trên bound chính
    for scenario in ("maker_base", "taker_worst"):
        base_m = out["scenarios"][scenario]["sl_first"]["metrics"]
        if base_m.get("n_trades", 0):
            res = run_backtest(ohlc, seg_signals, load_cost_model(fee_scale=1.5),
                               scenario=scenario, bound="sl_first", activity=act, funding=funding)
            m15 = compute_metrics(res.trades)
            out["scenarios"][scenario]["sl_first_fee_x1.5"] = {
                "expectancy_r": m15.get("expectancy_r"),
                "max_dd_pct": m15.get("max_dd_pct")}

    # --- Monte Carlo drawdown + random baseline trên bound chính, cả 2 kịch bản
    for scenario in ("maker_base", "taker_worst"):
        main = out["scenarios"][scenario]["sl_first"]
        m = main["metrics"]
        if not m.get("n_trades", 0):
            continue
        tr = None
        res = run_backtest(ohlc, seg_signals, load_cost_model(), scenario=scenario,
                           bound="sl_first", activity=act, funding=funding)
        tr = res.trades
        main["mc_drawdown"] = mc_drawdown(tr["r_net"].to_numpy(float), n_sims=1000)
        sl_pct = float(seg_signals["sl_pct"].iloc[0])
        tp_pct = float(seg_signals["tp_pct"].iloc[0])
        holding = int(seg_signals["holding_bars"].iloc[0])
        rb = random_baseline(ohlc, n_trades_target=m["n_trades"],
                             cost=load_cost_model(), scenario=scenario, bound="sl_first",
                             sl_pct=sl_pct, tp_pct=tp_pct, holding_bars=holding,
                             activity=act, k_seeds=30, funding=funding)
        main["random_baseline"] = rb
        main["edge_vs_random"] = edge_vs_random(m["expectancy_r"], rb)
    return out


def main() -> None:
    t_start = time.time()
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    news = load_news_calendar()

    # regime/attribution data
    sol_d1 = pd.read_parquet(DATA_DIR / "SOLUSDT_1d.parquet")
    sol_d1.index = pd.to_datetime(sol_d1["open_time"], unit="ms", utc=True)
    btc_d1 = pd.read_parquet(DATA_DIR / "BTCUSDT_1d.parquet")
    btc_d1.index = pd.to_datetime(btc_d1["open_time"], unit="ms", utc=True)
    reg = sol_regime(sol_d1)["regime"]
    bt = btc_d1_trend(btc_d1)["btc_trend"]

    signals = attach_sl_tp(conflict_resolver(generate_signals(sol)))
    logger.info(f"Tổng signals A/B/C sau conflict resolver: {len(signals)} "
                f"({signals['sid'].value_counts().to_dict()})")
    funding = FundingSchedule.load()
    start, end = pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")

    mask = split_mask(sol.index, SEGMENT)
    ohlc_seg = sol.loc[mask, ["open", "high", "low", "close"]]
    act_seg = activity_mask(ohlc_seg.index, news=news)
    seg_sig = signals[(signals["entry_time"] >= start) & (signals["entry_time"] <= end)]

    report: dict = {"segment": SEGMENT, "window": [str(start), str(end)],
                    "n_signals_segment": int(len(seg_sig)),
                    "signal_counts": seg_sig["sid"].value_counts().to_dict(),
                    "strategies": {}}
    for sid, grp in seg_sig.groupby("sid"):
        logger.info(f"=== {sid}: {len(grp)} signals ===")
        report["strategies"][sid] = run_one(sid, grp.reset_index(drop=True), ohlc_seg,
                                            act_seg, funding, reg, bt)

    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"Xong {time.time() - t_start:.0f}s → {REPORT}")


if __name__ == "__main__":
    main()
