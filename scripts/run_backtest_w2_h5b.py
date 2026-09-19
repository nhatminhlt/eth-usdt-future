"""WAVE 2 — H5b implementation (luật 12: event-study pass phải qua engine).

Pre-registered cấu hình (giống chuẩn đã lập từ M4c/M4d — không chỉnh sau khi thấy kết quả):
- Trigger: premium rank(30d) < 0.05 tại bar t (nguồn: premiumIndexKlines REST).
- Long tại close event bar (taker) / post-only tại low (maker, trade-through, patience 12).
- Holding 48 bar (knee decay curve: +0.180% t=4.22); TP KHÔNG; SL thiên tai = |MAE q05| 48-bar
  TRAIN events; flat cuối ngày; KHÔNG activity mask (luật 20); funding thật.
- Sizing cả hai chế độ (percent_risk 1% + governed cap 3% lev 1×) — contract SOL.
- Gates: settings.gates trên TRAIN (gross>0, net≥0.05R, CI>0, PF≥1.3, SQN≥2, n≥100, DD≤25%).
- VAL 2023-07→2024-06: cùng cấu hình, chấm expectancy cùng dấu.

Chạy: .venv/Scripts/python.exe scripts/run_backtest_w2_h5b.py
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
from solfut.backtest.metrics import compute_metrics, gates_check
from solfut.backtest.monte_carlo import mc_drawdown
from solfut.backtest.random_baseline import edge_vs_random, random_baseline
from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START = pd.Timestamp("2023-07-01", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HOLDING = 48
HID_IMPL = "H5b_impl"


def main() -> None:
    hl.register(hid=HID_IMPL,
                name="H5b implementation: premium rank<0.05 → long 4h horizon-exit, "
                     "SL thiên tai |MAE q05|, governed + percent-risk",
                source="H5b PASS event-study (t=4.17 @1h, drift @4h +0.180%)",
                criteria={"gate": "settings.gates trên TRAIN", "val": "expectancy cùng dấu"},
                segment="WAVE2_2020-10_2023-06")

    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    prem = pd.read_parquet(DATA_DIR / "premium" / "SOLUSDT_premium_5m.parquet")["premium"]
    p_rank = prem.reindex(sol.index).rolling(8640, min_periods=2880).rank(pct=True)
    mm = events.mfe_mae(sol["close"], sol["high"], sol["low"], HOLDING)
    funding = FundingSchedule.load()

    report: dict = {"hid": HID_IMPL, "holding": HOLDING, "segments": {}}
    sl_dis = None
    for seg, s0, s1 in (("TRAIN", T_START, T_END), ("VAL", V_START, V_END)):
        seg_mask = (sol.index >= s0) & (sol.index <= s1)
        ev_idx = sol.index[p_rank.lt(0.05).fillna(False) & seg_mask]
        if seg == "TRAIN":
            sl_dis = float(abs(mm.loc[ev_idx, "mae"].dropna().quantile(0.05)))
        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": HID_IMPL, "direction": 1,
            "entry_price": sol.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        seg_out: dict = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis, "runs": {}}
        logger.info(f"=== {seg}: {len(ev_idx)} events | SL {sl_dis:.4f} ===")
        for sizing_mode in ("percent_risk", "governed"):
            for scenario in ("maker_base", "taker_worst"):
                res = run_backtest(sol.loc[seg_mask, ["open", "high", "low", "close"]], sig,
                                   load_cost_model(), scenario=scenario, bound="sl_first",
                                   activity=None, funding=funding, equity_start=50.0,
                                   sizing=sizing_mode, risk_cap_pct=3.0, lev_cap_eff=1.0)
                m = compute_metrics(res.trades)
                g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
                seg_out["runs"][f"{sizing_mode}/{scenario}"] = {
                    "metrics": m, "gates": g, "engine_stats": res.stats}
                logger.info(f"{seg} {sizing_mode}/{scenario}: n={m.get('n_trades', 0)} "
                            f"expR={m.get('expectancy_r', float('nan')):.4f} "
                            f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                            f"PF={m.get('profit_factor_net', float('nan'))} "
                            f"ALL_PASS={g.get('ALL_PASS', {}).get('ok')}")
        # random baseline cho cấu hình chính (governed/taker)
        main_m = seg_out["runs"]["governed/taker_worst"]["metrics"]
        if main_m.get("n_trades", 0):
            res = run_backtest(sol.loc[seg_mask, ["open", "high", "low", "close"]], sig,
                               load_cost_model(), scenario="taker_worst", bound="sl_first",
                               activity=None, funding=funding, equity_start=50.0,
                               sizing="governed", risk_cap_pct=3.0, lev_cap_eff=1.0)
            seg_out["runs"]["governed/taker_worst"]["mc_drawdown"] = \
                mc_drawdown(res.trades["r_net"].to_numpy(float), n_sims=1000)
            rb = random_baseline(sol.loc[seg_mask, ["open", "high", "low", "close"]],
                                 n_trades_target=main_m["n_trades"], cost=load_cost_model(),
                                 scenario="taker_worst", bound="sl_first", sl_pct=sl_dis,
                                 tp_pct=np.nan, holding_bars=HOLDING, activity=None,
                                 k_seeds=30, funding=funding)
            seg_out["runs"]["governed/taker_worst"]["random_baseline"] = rb
            seg_out["runs"]["governed/taker_worst"]["edge_vs_random"] = \
                edge_vs_random(main_m["expectancy_r"], rb)
        report["segments"][seg] = seg_out

    tr_ok = report["segments"]["TRAIN"]["runs"]["governed/taker_worst"]["gates"].get("ALL_PASS", {}).get("ok")
    tr_maker = report["segments"]["TRAIN"]["runs"]["governed/maker_base"]["gates"].get("ALL_PASS", {}).get("ok")
    val_exp = report["segments"]["VAL"]["runs"]["governed/taker_worst"]["metrics"].get("expectancy_r")
    val_maker = report["segments"]["VAL"]["runs"]["governed/maker_base"]["metrics"].get("expectancy_r")
    verdict = "pass" if ((tr_ok or tr_maker) and (val_exp is not None and val_exp > 0)) else "kill"
    hl.record_verdict(HID_IMPL, verdict, {
        "train_all_pass_taker": tr_ok, "train_all_pass_maker": tr_maker,
        "val_expectancy_r_taker": val_exp, "val_expectancy_r_maker": val_maker,
        "sl_disaster_pct": sl_dis,
    })
    report["verdict"] = verdict
    out = DATA_DIR / "reports" / "w2_h5b_impl.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"VERDICT: {verdict} → {out}")


if __name__ == "__main__":
    main()
