"""W4 — H9 implementation (luật 12): RSI(14) 5m < 30 → long, holding 48 bar (4h).

Cấu hình pre-registered (TRƯỚC KHI CHẠY — gate settings.gates KHÔNG đổi):
- Trigger: rsi14 < 30 tại bar t (enriched dataset — RSI causal có sẵn).
- Entry: close event bar (taker) / post-only tại low event bar (maker, trade-through).
- Holding 48 bar (decay curve @4h t=6.55; @8h t=9.12 nhưng 8h xung đột flat-EOD — ghi nhận
  là follow-up nếu 4h pass).
- TP KHÔNG; SL thiên tai = |MAE q05| 48-bar TRAIN events; partial-BE: chốt 50% tại
  partial_pct = median MFE 48-bar TRAIN events (touch fill, maker), SL phần còn lại → BE.
- Exit time/EOD bằng post-only limit (trade-through, patience 12, fallback market).
- Governed sizing cap 3% lev 1×; funding thật; flat cuối ngày; KHÔNG activity mask (luật 20).
- Kịch bản chính: maker/maker; taker-entry báo cáo minh bạch.
- TRAIN gate → VAL chấm expectancy cùng dấu. KHÔNG đụng OOS.

Chạy: .venv/Scripts/python.exe scripts/run_w4_h9_impl.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.backtest.costs import FundingSchedule, load_cost_model
from solfut.backtest.engine import run_backtest
from solfut.backtest.metrics import bootstrap_expectancy_ci, compute_metrics, gates_check
from solfut.backtest.monte_carlo import mc_drawdown
from solfut.backtest.random_baseline import edge_vs_random, random_baseline
from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

HOLDING = 48
T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START = pd.Timestamp("2023-07-01", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HID_IMPL = "H9_impl_rsi_oversold"


def main() -> None:
    hl.register(hid=HID_IMPL,
                name="H9 implementation: RSI<30 → long 4h, partial-BE (50% tại median MFE, "
                     "SL còn lại → BE), SL thiên tai |MAE q05|, maker/maker, governed",
                source="H9 PASS event-study (t=6.55 @4h, t=9.12 @8h, VAL +0.104%)",
                criteria={"gate": "settings.gates trên TRAIN", "val": "expectancy cùng dấu"},
                segment="WAVE3_2020-10_2025-08")

    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    mask_all = sol["rsi14"].lt(30).fillna(False)
    mm = events.mfe_mae(sol["close"], sol["high"], sol["low"], HOLDING)
    funding = FundingSchedule.load()

    # derive SL/partial trên TRAIN (một lần, dùng cho cả VAL — không re-fit)
    tr_idx = sol.index[(sol.index >= T_START) & (sol.index <= T_END)]
    ev_tr = tr_idx[mask_all.loc[tr_idx]]
    sl_dis = float(abs(mm.loc[ev_tr, "mae"].dropna().quantile(0.05)))
    partial_pct = float(mm.loc[ev_tr, "mfe"].dropna().median())
    logger.info(f"H9 TRAIN events: {len(ev_tr)} | SL disaster {sl_dis:.4f} | "
                f"partial (median MFE) {partial_pct:.4f}")

    report: dict = {"hid": HID_IMPL, "holding": HOLDING, "sl_disaster_pct": sl_dis,
                    "partial_pct": partial_pct, "segments": {}}
    for seg, s0, s1 in (("TRAIN", T_START, T_END), ("VAL", V_START, V_END)):
        seg_mask = (sol.index >= s0) & (sol.index <= s1)
        ev_idx = sol.index[mask_all & seg_mask]
        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": HID_IMPL, "direction": 1,
            "entry_price": sol.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        seg_out: dict = {"n_events": int(len(ev_idx)), "runs": {}}
        logger.info(f"=== {seg}: {len(ev_idx)} events ===")
        for entry in ("maker_base", "taker_worst"):
            res = run_backtest(sol.loc[seg_mask, ["open", "high", "low", "close"]], sig,
                               load_cost_model(), scenario=entry, bound="sl_first",
                               activity=None, funding=funding, equity_start=50.0,
                               sizing="governed", risk_cap_pct=3.0, lev_cap_eff=1.0,
                               exit_maker=True, exit_patience=12,
                               partial_be=True, partial_pct=partial_pct)
            m = compute_metrics(res.trades)
            g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
            seg_out["runs"][entry] = {"metrics": m, "gates": g, "engine_stats": res.stats}
            logger.info(f"{seg}/{entry}: n={m.get('n_trades', 0)} expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                        f"costR={m.get('cost_r', float('nan')):.4f} PF={m.get('profit_factor_net', float('nan'))} "
                        f"SQN={m.get('sqn_r', float('nan'))} dd95="
                        f"{mc_drawdown(res.trades['r_net'].to_numpy(float), n_sims=500).get('max_dd_p95') if len(res.trades) else None} "
                        f"partialFill={res.stats.get('partial_fill_rate')} "
                        f"ALL_PASS={g.get('ALL_PASS', {}).get('ok')}")
            logger.info(f"    exits={m.get('exit_reasons')} tpY={m.get('trades_per_year', 0):.0f}")
            if entry == "maker_base" and seg == "TRAIN" and m.get("n_trades", 0):
                rb = random_baseline(sol.loc[seg_mask, ["open", "high", "low", "close"]],
                                     n_trades_target=m["n_trades"], cost=load_cost_model(),
                                     scenario=entry, bound="sl_first", sl_pct=sl_dis,
                                     tp_pct=np.nan, holding_bars=HOLDING, activity=None,
                                     k_seeds=30, funding=funding)
                seg_out["runs"][entry]["edge_vs_random"] = edge_vs_random(m["expectancy_r"], rb)
                logger.info(f"    edge_vs_random={seg_out['runs'][entry]['edge_vs_random']}")
        report["segments"][seg] = seg_out

    tr_ok = report["segments"]["TRAIN"]["runs"]["maker_base"]["gates"].get("ALL_PASS", {}).get("ok")
    tr_taker = report["segments"]["TRAIN"]["runs"]["taker_worst"]["gates"].get("ALL_PASS", {}).get("ok")
    val_exp = report["segments"]["VAL"]["runs"]["maker_base"]["metrics"].get("expectancy_r")
    verdict = "pass" if ((tr_ok or tr_taker) and val_exp is not None and val_exp > 0) else "kill"
    hl.record_verdict(HID_IMPL, verdict, {
        "train_all_pass_maker": tr_ok, "train_all_pass_taker": tr_taker,
        "val_expectancy_r_maker": val_exp,
        "sl_disaster_pct": sl_dis, "partial_pct": partial_pct,
    })
    report["verdict"] = verdict
    out = DATA_DIR / "reports" / "w4_h9_impl.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"VERDICT: {verdict} → {out}")


if __name__ == "__main__":
    main()
