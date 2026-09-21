"""W8-DIAGNOSTIC — KHÔNG PHẢI ỨNG VIÊN. 12/12 atom W8 đã kill ở tầng drift; script này
chạy engine trên 2 atom đại diện (bộ intraday EMA-stack+VWAP pullback, bộ swing RSI50+EMA200)
duy nhất để ĐỊNH LƯỢNG gross→net sau phí thật — trả lời câu hỏi audit của user:
"phí có đúng thực tế, chiến lược có được code đúng, có tradeable sau phí không".

Không ghi hypothesis ledger (không phải giả thuyết — avoid ledger churn); output JSON riêng.
SL/TP derive đúng công thức framework: SL = |MAE q05| TRAIN, TP = MFE q75 TRAIN,
holding = horizon đã đăng ký (+1h=12 bar 5m; +4h=4 bar 1h). Scenario cả hai; primary:
pullback = maker_base (entry limit), momentum = taker_worst (entry market — execution thật).

Chạy: .venv/Scripts/python.exe scripts/run_w8_impl_diagnostic.py
Output: data/reports/w8_impl_diagnostic.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from loguru import logger

from run_event_study_w8_indicator_atoms import build_masks_1h, build_masks_5m

from solfut.backtest.costs import FundingSchedule, load_cost_model
from solfut.backtest.engine import run_backtest
from solfut.backtest.metrics import compute_metrics, gates_check
from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")

DIAG = [
    # (hid, frame, holding_bars, primary_scenario)
    ("W8a_ema_stack_pullback_long", "5m", 12, "maker_base"),
    ("W8a_ema_stack_pullback_short", "5m", 12, "maker_base"),
    ("W8e_rsi50_trend_long", "1h", 4, "taker_worst"),
]


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=3)]
    h1 = load_monthlies("SOLUSDT", "1h")
    for col in ("open", "high", "low", "close", "volume"):
        h1[col] = pd.to_numeric(h1[col], errors="coerce")
    h1.index = pd.to_datetime(h1["open_time"], unit="ms", utc=True)
    h1 = h1.sort_index()
    h1 = h1[h1.index <= V_END + pd.Timedelta(days=3)]

    masks5 = build_masks_5m(sol)
    masks1 = build_masks_1h(h1)
    funding = FundingSchedule.load("SOLUSDT")
    cost = load_cost_model()
    contract = {"lot_step": 0.01, "min_qty": 0.01, "min_notional": 5.0, "leverage_cap": 5}

    report: dict = {"note": "DIAGNOSTIC — drift-killed atoms; quantify cost drag only, NOT candidates"}
    for hid, frame, holding, primary in DIAG:
        df = sol if frame == "5m" else h1
        mask = (masks5 if frame == "5m" else masks1)[hid]
        direction = -1 if hid.endswith("short") else +1

        # derive SL/TP từ TRAIN event distribution (deterministic)
        # quy về hướng trade: mae_dir âm = đi ngược hướng (bất lợi), mfe_dir dương = có lợi
        tr_m = mask & (df.index >= T_START) & (df.index <= T_END)
        ev = df.index[tr_m]
        mm = events.mfe_mae(df["close"], df["high"], df["low"], holding)
        mae_dir = mm.loc[ev, "mae"] if direction > 0 else -mm.loc[ev, "mfe"]
        mfe_dir = mm.loc[ev, "mfe"] if direction > 0 else -mm.loc[ev, "mae"]
        sl_pct = float(-mae_dir.dropna().quantile(0.05))     # khoảng cách SL dương
        tp_pct = float(mfe_dir.dropna().quantile(0.75))      # TP dương theo hướng
        assert sl_pct > 0 and tp_pct > 0, (sl_pct, tp_pct)

        report[hid] = {"frame": frame, "sl_pct": sl_pct, "tp_pct": tp_pct,
                       "holding_bars": holding, "segments": {}}
        for seg, (s, e) in {"TRAIN": (T_START, T_END), "VAL": (T_END, V_END)}.items():
            seg_m = mask & (df.index > (T_END if seg == "VAL" else T_START - pd.Timedelta(days=2))) \
                    & (df.index <= e + pd.Timedelta(days=2))
            ev_idx = df.index[seg_m & (df.index <= e)]
            sig = pd.DataFrame({
                "entry_time": ev_idx, "sid": hid, "direction": direction,
                "entry_price": df.loc[ev_idx, "close"].values,
                "sl_pct": sl_pct, "tp_pct": tp_pct, "holding_bars": holding,
            })
            df_seg = df[(df.index >= (T_START if seg == "TRAIN" else T_END)) & (df.index <= e + pd.Timedelta(days=3))]
            runs = {}
            for scenario in ("maker_base", "taker_worst"):
                res = run_backtest(df_seg, sig, cost, scenario=scenario, bound="sl_first",
                                   activity=None, patience_bars=12, funding=funding,
                                   equity_start=50.0, sizing="percent_risk", contract=contract)
                m = compute_metrics(res.trades)
                runs[scenario] = {"metrics": m, "engine_stats": res.stats,
                                  "gates": gates_check(m) if m.get("n_trades") else {}}
            report[hid]["segments"][seg] = runs
            for scenario, rr in runs.items():
                m = rr["metrics"]
                logger.info(f"{hid}/{seg}/{scenario}: n={m.get('n_trades', 0)} "
                            f"grossR={m.get('gross_expectancy_r', float('nan')):+.4f} "
                            f"netR={m.get('expectancy_r', float('nan')):+.4f} "
                            f"costR={m.get('cost_r', float('nan')):.4f} "
                            f"PF={m.get('profit_factor_net', float('nan')):.3f} "
                            f"fill={rr['engine_stats'].get('fill_rate_maker')}")
        prim = report[hid]["segments"]["TRAIN"][primary]["metrics"]
        logger.info(f"== {hid} PRIMARY({primary}) TRAIN: net {prim.get('expectancy_r', float('nan')):+.4f}R — "
                    f"gates ALL_PASS={report[hid]['segments']['TRAIN'][primary]['gates'].get('ALL_PASS', {}).get('ok')}")

    out = DATA_DIR / "reports" / "w8_impl_diagnostic.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
