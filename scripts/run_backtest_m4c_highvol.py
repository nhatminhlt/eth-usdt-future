"""M4c — Ứng viên edge #1 (pre-registered): A2_seesaw_highvol_4h.

Nguồn: diagnostic_decay_regimes (attribution thuần của H2b ĐÃ PASS — không phải grid mới):
decay H2b tăng đơn điệu; tầng ATR-percentile>70 (30 ngày rolling) excess +0.83% @4h t=9.1 n=2995,
trong khi ATR≤70 ≈ 0/âm. Mechanism a-priori: bounce seesaw sau BTC flash-drop chỉ tồn tại khi
SOL đang ở regime vol cao (panic) — vol thấp thì BTC dip là nhiễu kéo theo (đúng dấu chấm trên
dữ liệu). PLAN M2.5: "edge chỉ tồn tại ở 1 regime → biến thành chiến thuật regime-conditional";
holding ĐẾN TỪ decay curve ("không để grid quyết định") = 48 bar; TP BỎ (M4b chứng minh bracket
rò rỉ); SL thiên tai = |MAE q05| của SUBSET (derive từ MFE/MAE theo PLAN M2.5).

Pre-registered criteria (TRƯỚC KHI CHẠY — gate settings.gates trên TRAIN):
  gross>0; net expectancy ≥ 0.05R; CI95 (moving-block) > 0; PF_net ≥ 1.3; SQN ≥ 2.0;
  n ≥ 100; maxDD ≤ 25%; trades/năm ≥ 300 (informational).
VAL chỉ chấm GIỮ HƯỚNG (excess dương) — chạy SAU khi có verdict TRAIN.

Chạy: .venv/Scripts/python.exe scripts/run_backtest_m4c_highvol.py
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
from solfut.features.sessions import activity_mask, load_news_calendar
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask
from solfut.strategies.base import conflict_resolver
from solfut.strategies.hypothesis_fades import generate_signals

HID = "A2_seesaw_highvol_4h"
T_START, T_END = pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START, V_END = pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-06-30 23:59", tz="UTC")
HOLDING = 48


def build_signals(sol: pd.DataFrame) -> pd.DataFrame:
    """Trigger H2b (BTC 5m ≤ −2σ) + filter atrPct>70; holding 48; SL/TP điền sau."""
    sig = generate_signals(sol)
    a = sig[sig["sid"] == "A_seesaw_long"].copy()
    atr_pct = sol["atr14"].rolling(8640).rank(pct=True)
    a["keep"] = atr_pct.loc[a["entry_time"]].values > 0.70
    a = a[a["keep"]].drop(columns=["keep"])
    a["sid"] = "A2_seesaw_highvol_4h"
    a["holding_bars"] = HOLDING
    return a.reset_index(drop=True)


def main() -> None:
    # ---- PRE-REGISTER TRƯỚC KHI CHẠY (idempotent)
    hl.register(hid=HID,
                name="A2 seesaw high-vol 4h: H2b trigger + atrPct(30d)>70, holding 48 bar, "
                     "horizon exit, SL thiên tai |MAE q05| của subset",
                source="Attribution của H2b (PASS) — mechanism: seesaw bounce chỉ ở regime vol cao",
                criteria={"gate": "settings.gates trên TRAIN (gross>0, net≥0.05R, CI>0, PF≥1.3, "
                                  "SQN≥2, n≥100, DD≤25%)", "val": "excess @4h giữ hướng dương"},
                segment="TRAIN_2020-10_2023-06")

    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    news = load_news_calendar()
    sig_all = build_signals(sol)
    logger.info(f"A2 events: TRAIN={int(split_mask(pd.DatetimeIndex(sig_all['entry_time']), 'TRAIN').sum())} "
                f"VAL={int(split_mask(pd.DatetimeIndex(sig_all['entry_time']), 'VAL').sum())}")

    funding = FundingSchedule.load()
    report: dict = {"hid": HID, "holding_bars": HOLDING, "segments": {}}

    for seg, s0, s1 in (("TRAIN", T_START, T_END), ("VAL", V_START, V_END)):
        mask = split_mask(sol.index, seg)
        ohlc = sol.loc[mask, ["open", "high", "low", "close"]]
        act = activity_mask(ohlc.index, news=news)
        sig_seg = sig_all[sig_all["entry_time"].between(s0, s1)].reset_index(drop=True)
        if len(sig_seg) == 0:
            report["segments"][seg] = {"n_events": 0}
            continue

        # SL thiên tai = |MAE q05| của SUBSET đo trên TRAIN (VAL dùng cùng con số — không re-fit)
        mm = events.mfe_mae(sol["close"], sol["high"], sol["low"], HOLDING)
        if seg == "TRAIN":
            mae_ev = mm.loc[sig_seg["entry_time"], "mae"].dropna()
            sl_disaster = float(abs(mae_ev.quantile(0.05)))
            report["sl_disaster_pct"] = sl_disaster
        else:
            sl_disaster = report["sl_disaster_pct"]
        sig_seg["sl_pct"] = sl_disaster
        sig_seg["tp_pct"] = np.nan
        logger.info(f"=== {seg}: {len(sig_seg)} events | SL disaster {sl_disaster:.4f} ===")

        seg_out: dict = {"n_events": int(len(sig_seg)), "scenarios": {}}
        for scenario in ("maker_base", "taker_worst"):
            res = run_backtest(ohlc, sig_seg, load_cost_model(), scenario=scenario,
                               bound="sl_first", activity=act, funding=funding)
            m = compute_metrics(res.trades)
            g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
            mc = mc_drawdown(res.trades["r_net"].to_numpy(float), n_sims=1000) if len(res.trades) else {}
            rb = random_baseline(ohlc, n_trades_target=m.get("n_trades", 0), cost=load_cost_model(),
                                 scenario=scenario, bound="sl_first", sl_pct=sl_disaster, tp_pct=np.nan,
                                 holding_bars=HOLDING, activity=act, k_seeds=30, funding=funding) \
                if m.get("n_trades", 0) else {}
            seg_out["scenarios"][scenario] = {
                "metrics": m, "gates": g, "engine_stats": res.stats, "mc_drawdown": mc,
                "random_baseline": rb, "edge_vs_random": edge_vs_random(m.get("expectancy_r", 0), rb)}
            logger.info(f"{seg} {scenario}: n={m.get('n_trades', 0)} expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} costR={m.get('cost_r', float('nan')):.4f} "
                        f"PF={m.get('profit_factor_net', float('nan'))} SQN={m.get('sqn_r', float('nan'))} "
                        f"win={m.get('win_rate', float('nan')):.2f} dd95={mc.get('max_dd_p95')} "
                        f"ALL_PASS={g.get('ALL_PASS', {}).get('ok')}")
            if len(res.trades):
                logger.info(f"    exits={m.get('exit_reasons')} tpY={m.get('trades_per_year'):.0f} "
                            f"edge_vs_random={seg_out['scenarios'][scenario]['edge_vs_random'].get('edge_r')}")
        report["segments"][seg] = seg_out

    # ---- verdict TRAIN theo gate; VAL chỉ giữ hướng
    tr = report["segments"]["TRAIN"]
    best = max(tr["scenarios"].values(), key=lambda d: d["metrics"].get("expectancy_r") or -9)
    train_ok = best["gates"].get("ALL_PASS", {}).get("ok", False)
    val = report["segments"].get("VAL", {})
    val_ok = None
    if val.get("n_events", 0):
        # VAL: excess @4h của subset theo phép đo event-study (giữ hướng)
        sol_val = sol.loc[split_mask(sol.index, "VAL")]
        fwd = sol_val["close"].shift(-HOLDING) / sol_val["close"] - 1
        ev = sig_all[sig_all["entry_time"].between(V_START, V_END)]["entry_time"]
        ev_fwd = fwd.loc[ev].dropna()
        base = fwd.dropna().mean()
        val_ex = float((ev_fwd.mean() - base) * 100)
        val_ok = val_ex > 0
        report["segments"]["VAL"]["excess_4h_pct"] = val_ex
        report["segments"]["VAL"]["n_val_events_scored"] = int(len(ev_fwd))
        logger.info(f"VAL excess @4h = {val_ex:+.3f}% → giữ hướng: {val_ok}")

    verdict = "pass" if (train_ok and (val_ok is not False)) else "kill"
    report["verdict"] = verdict
    hl.record_verdict(HID, verdict, {
        "train_best_scenario_expectancy_r": best["metrics"].get("expectancy_r"),
        "train_all_pass": train_ok,
        "val_excess_4h_pct": report["segments"].get("VAL", {}).get("excess_4h_pct"),
        "val_keep_direction": val_ok,
        "sl_disaster_pct": report.get("sl_disaster_pct"),
    })
    out = DATA_DIR / "reports" / "m4c_highvol.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"VERDICT: {verdict} → {out}")


if __name__ == "__main__":
    main()
