"""M4b — Biến thể exit-structure DUY NHẤT (pre-registered): horizon exit.

Lý do (evidence từ m4_backtest_train.json): bracket SL=|MAE q25| / TP=MFE q75 khơi SL 26–47% số lệnh
mỗi lần −1R trong khi drift đo được chỉ +0.08–0.16%/event → gross ≈ 0 trước phí. Random baseline cùng
bracket thua −0.08…−0.28R → chính cấu trúc thoát là chỗ rò rỉ. Event study đo close-to-close tại
horizon → biến thể giao dịch ĐÚNG theo phép đo: KHÔNG TP, thoát tại close[t + holding], SL chỉ là
thiên tai tại |MAE q05| (bảo toàn sizing, không phải mục tiêu giao dịch).

Đây là 1 biến thể duy nhất cho mỗi chiến thuật — không phải grid ("tinh chỉnh đến khi lãi" = vi phạm
luật 13). Chấm gate TRAIN ngay trong script, ghi vào hypothesis ledger.

Chạy: .venv/Scripts/python.exe scripts/run_backtest_m4b_horizon.py
Output: data/reports/m4_backtest_train_horizon.json (+ ledger append)
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
from solfut.backtest.metrics import compute_metrics, gates_check
from solfut.backtest.monte_carlo import mc_drawdown
from solfut.backtest.random_baseline import edge_vs_random, random_baseline
from solfut.data.downloader import DATA_DIR
from solfut.features.sessions import activity_mask, load_news_calendar
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask
from solfut.strategies.base import conflict_resolver
from solfut.strategies.hypothesis_fades import generate_signals

SEGMENT = "TRAIN"
REPORT = DATA_DIR / "reports" / f"m4_backtest_{SEGMENT.lower()}_horizon.json"
LEDGER = DATA_DIR / "reports" / "hypothesis_ledger.jsonl"


def main() -> None:
    t0 = time.time()
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    news = load_news_calendar()

    signals = conflict_resolver(generate_signals(sol))          # event set gốc (chưa SL/TP bracket)
    logger.info(f"Signals: {signals['sid'].value_counts().to_dict()}")

    # --- PRE-REGISTER 3 variant TRƯỚC KHI CHẠY (kỷ luật ledger; register idempotent)
    VARIANT_SIDS = list(signals["sid"].unique())
    for sid in VARIANT_SIDS:
        hl.register(hid=f"M4HORIZON_{sid}",
                    name=f"{sid} horizon-exit variant: không TP, SL thiên tai |MAE q05|, "
                         f"thoát close[t+holding] — đúng theo phép đo event-study",
                    source="M4b exit-structure revision (1 biến thể/chiến thuật, pre-registered)",
                    criteria={"same_as": "settings.gates trên TRAIN (gross>0 bắt buộc, "
                                         "net>0.05R, CI>0, PF, SQN, n, DD) — chấm theo kịch bản "
                                         "tốt hơn sau khi thấy cả 2 (quy tắc chọn execution vòng 8)"},
                    segment="TRAIN_2020-10_2023-06")

    # MAE/MFE tại các event theo SID (48 bar — khung đo của event study)
    mm = events.mfe_mae(sol["close"], sol["high"], sol["low"], 48)
    funding = FundingSchedule.load()
    start, end = pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")
    mask = split_mask(sol.index, SEGMENT)
    ohlc_seg = sol.loc[mask, ["open", "high", "low", "close"]]
    act_seg = activity_mask(ohlc_seg.index, news=news)

    report: dict = {"segment": SEGMENT, "variant": "horizon_exit (no TP, disaster SL=|MAE q05|)",
                    "strategies": {}}
    for sid, grp in signals.groupby("sid"):
        ev = grp[grp["entry_time"].between(start, end)]
        mfe_ev = mm.loc[ev["entry_time"], "mfe"].dropna()
        mae_ev = mm.loc[ev["entry_time"], "mae"].dropna()
        sl_disaster = float(abs(mae_ev.quantile(0.05)))
        variant = ev.copy()
        variant["sl_pct"] = sl_disaster
        variant["tp_pct"] = np.nan
        logger.info(f"=== {sid}: {len(ev)} events | SL disaster (MAE q05) = {sl_disaster:.4f} "
                    f"(q25 ref {abs(mae_ev.quantile(0.25)):.4f}) ===")

        out: dict = {"sl_disaster_pct": sl_disaster, "n_events": int(len(ev)), "scenarios": {}}
        for scenario in ("maker_base", "taker_worst"):
            res = run_backtest(ohlc_seg, variant.reset_index(drop=True), load_cost_model(),
                               scenario=scenario, bound="sl_first", activity=act_seg, funding=funding)
            m = compute_metrics(res.trades)
            g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
            mc = mc_drawdown(res.trades["r_net"].to_numpy(float), n_sims=1000) if len(res.trades) else {}
            rb = random_baseline(ohlc_seg, n_trades_target=m.get("n_trades", 0),
                                 cost=load_cost_model(), scenario=scenario, bound="sl_first",
                                 sl_pct=sl_disaster, tp_pct=np.nan,
                                 holding_bars=int(ev["holding_bars"].iloc[0]),
                                 activity=act_seg, k_seeds=30, funding=funding) \
                if m.get("n_trades", 0) else {}
            out["scenarios"][scenario] = {"metrics": m, "gates": g, "mc_drawdown": mc,
                                          "engine_stats": res.stats,
                                          "random_baseline": rb,
                                          "edge_vs_random": edge_vs_random(m.get("expectancy_r", 0), rb)}
            logger.info(f"{sid} {scenario}: n={m.get('n_trades', 0)} expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                        f"costR={m.get('cost_r', float('nan')):.4f} PF={m.get('profit_factor_net', float('nan'))} "
                        f"win={m.get('win_rate', float('nan')):.2f} ALL_PASS={g.get('ALL_PASS', {}).get('ok')}")
            logger.info(f"    exits={m.get('exit_reasons')} mc_dd_p95={mc.get('max_dd_p95')}")
        report["strategies"][sid] = out

    # --- ghi ledger: verdict variant theo gate TRAIN; kịch bản tốt hơn theo net expectancy
    for sid, out in report["strategies"].items():
        cand = []
        for scenario, d in out["scenarios"].items():
            g = d["gates"]
            all_pass = g.get("ALL_PASS", {}).get("ok", False)
            cand.append((d["metrics"].get("expectancy_r") or -9, scenario, all_pass, d))
        best_exp, best_sc, best_pass, best = max(cand, key=lambda x: x[0])
        hl.record_verdict(f"M4HORIZON_{sid}", "pass" if best_pass else "kill", {
            "chosen_scenario": best_sc,
            "per_scenario": {sc: {"n_trades": d["metrics"].get("n_trades", 0),
                                  "expectancy_r": d["metrics"].get("expectancy_r"),
                                  "gross_expectancy_r": d["metrics"].get("gross_expectancy_r"),
                                  "profit_factor_net": d["metrics"].get("profit_factor_net"),
                                  "sqn_r": d["metrics"].get("sqn_r"),
                                  "max_dd_pct": d["metrics"].get("max_dd_pct"),
                                  "gates_all_pass": d["gates"].get("ALL_PASS", {}).get("ok", False),
                                  "edge_vs_random_r": d["edge_vs_random"].get("edge_r")}
                             for sc, d in out["scenarios"].items()},
            "sl_disaster_pct": out["sl_disaster_pct"],
        })

    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"Xong {time.time() - t0:.0f}s → {REPORT}")


if __name__ == "__main__":
    main()
