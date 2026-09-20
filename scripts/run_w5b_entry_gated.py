"""W5 bước 2 — Entry-gated stress ensemble (chiến lược live: CHỈ vào event có ATR14-5m ≥ 0.8%).

Cấu hình frozen (khác cấu hình M4d duy nhất ở 1 điều kiện entry thêm — ghi rõ):
H2b trigger × atrRank30d>0.70 × **atrAbs≥0.80%** → long, holding 48, horizon exit, SL thiên tai
|MAE q05| TRAIN (derive trên event set đầy đủ, như trước), governed cap 3% lev 1×, maker/maker.

Pre-registered bar-cell check trước khi tiêu OOS2 (sau khi thấy TRAIN/VAL/OOS1 entry-gated):
  TRAIN: CI95 lo > 0 và expectancy ≥ 0.05R, n ≥ 500
  VAL:   expectancy > 0
  OOS1:  expectancy > 0 và CI95 lo > 0
CHỈ khi cả 3 pass → OOS2 one-shot (xcriteria riêng sẽ pre-register trước đó).
Khác biệt so với bảng post-hoc (run_w5_stress_attribution): gate tại entry đổi selection
(single-position slot) — số có thể lệch nhẹ, đây là con số của chiến lược thật.

Chạy: .venv/Scripts/python.exe scripts/run_w5b_entry_gated.py
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
from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
HOLDING = 48
SEGMENTS = {
    "TRAIN": (pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")),
    "VAL": (pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-06-30 23:59", tz="UTC")),
    "OOS1": (pd.Timestamp("2024-07-01", tz="UTC"), pd.Timestamp("2025-08-31 23:59", tz="UTC")),
}
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0
ATR_GATE = 0.80      # % — entry gate cứng


def load_5m(symbol: str) -> pd.DataFrame:
    df = load_monthlies(symbol, "5m")
    df = df[["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"]].copy()
    for c in ("open", "high", "low", "close", "volume", "taker_buy_volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.sort_index()


def btc_jump_mask(index: pd.DatetimeIndex) -> pd.Series:
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    ret = btc["close"].pct_change()
    sigma = ret.rolling(96).std()
    return (ret <= -2 * sigma).reindex(index).fillna(False)


def abs_atr_pct(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return (tr.rolling(14).mean() / df["close"] * 100)


def portfolio_metrics(tr: pd.DataFrame) -> dict:
    eq = len(SYMBOLS) * 50.0 + tr["net_pnl"].cumsum()
    peak = np.maximum.accumulate(np.concatenate([[len(SYMBOLS) * 50.0], eq.values]))[1:]
    dd = float(((peak - eq.values) / peak * 100).max())
    r = tr["r_net"].to_numpy(float)
    lo, hi = bootstrap_expectancy_ci(r)
    span_years = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
    return {
        "n_trades": int(len(tr)), "expectancy_r": float(np.nanmean(r)),
        "gross_expectancy_r": float(np.nanmean(tr["r_gross"])),
        "ci95": [lo, hi],
        "profit_factor_net": float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                                   / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
        if (tr["net_pnl"] <= 0).any() else float("inf"),
        "sqn_r": float(np.sqrt(len(r)) * np.nanmean(r) / np.nanstd(r, ddof=1)),
        "max_dd_pct": dd, "equity_end": float(eq.iloc[-1]),
        "total_net_usdt": float(tr["net_pnl"].sum()),
        "win_rate": float((tr["net_pnl"] > 0).mean()),
        "trades_per_year": float(len(tr) / span_years),
        "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
    }


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    report: dict = {"config": "ensemble-8 ENTRY-GATED atrAbs≥0.80% — rest frozen M4d/W3",
                    "segments": {}, "by_symbol": {}}
    sl_by_sym: dict = {}
    all_pockets: dict = {}
    for seg, (s0, s1) in SEGMENTS.items():
        all_tr = []
        for sym in SYMBOLS:
            try:
                df = load_5m(sym)
            except FileNotFoundError:
                logger.warning(f"{sym}: thiếu dữ liệu — bỏ qua")
                continue
            atr_abs = abs_atr_pct(df)
            atr_rank = atr_abs.rolling(8640, min_periods=2880).rank(pct=True)
            df_seg = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
            rank_seg = atr_rank.loc[df_seg.index]
            unb0 = btc_jump_mask(df_seg.index) & rank_seg.gt(0.70).fillna(False)
            ev_idx = df_seg.index[unb0 & (df_seg.index <= s1)]
            # --- ENTRY GATE (điểm mới) ---
            ev_idx = ev_idx[atr_abs.loc[ev_idx] >= ATR_GATE]

            if seg == "TRAIN" and sym not in sl_by_sym:
                df_tr = df[(df.index >= SEGMENTS["TRAIN"][0])
                           & (df.index <= SEGMENTS["TRAIN"][1] + pd.Timedelta(days=2))]
                rank_tr = atr_rank.loc[df_tr.index]
                mask_tr = btc_jump_mask(df_tr.index) & rank_tr.gt(0.70).fillna(False)
                ev_tr = df_tr.index[mask_tr]
                mm = events.mfe_mae(df_tr["close"], df_tr["high"], df_tr["low"], HOLDING)
                sl_by_sym[sym] = float(abs(mm.loc[ev_tr, "mae"].dropna().quantile(0.05)))
            sl_dis = sl_by_sym.get(sym)
            if not sl_dis:
                continue

            sig = pd.DataFrame({
                "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
                "entry_price": df_seg.loc[ev_idx, "close"].values,
                "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
            })
            res = run_backtest(df_seg, sig, load_cost_model(), scenario="maker_base",
                               bound="sl_first", activity=None,
                               funding=FundingSchedule.load(sym), equity_start=50.0,
                               sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                               lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                               exit_maker=True, exit_patience=12)
            if len(res.trades):
                all_tr.append(res.trades.assign(symbol=sym))
                report["by_symbol"].setdefault(sym, {})[seg] = \
                    {"n": int(len(res.trades)),
                     "expectancy_r": float(res.trades["r_net"].mean())}
        if all_tr:
            tr = pd.concat(all_tr, ignore_index=True).sort_values("exit_time")
            pm = portfolio_metrics(tr)
            pm["gates"] = gates_check(pm)
            report["segments"][seg] = {"portfolio": pm}
            all_pockets[seg] = tr
            g = pm["gates"]
            logger.info(f"[{seg}] ENTRY-GATED PORTFOLIO-8: n={pm['n_trades']} "
                        f"expR={pm['expectancy_r']:.4f} CI=[{pm['ci95'][0]:.4f},{pm['ci95'][1]:.4f}] "
                        f"PF={pm['profit_factor_net']:.2f} SQN={pm['sqn_r']:.2f} DD={pm['max_dd_pct']:.1f}% "
                        f"net={pm['total_net_usdt']:.2f} tpY={pm['trades_per_year']:.0f} "
                        f"ALL_PASS={g['ALL_PASS']['ok']}")

    # ===== pre-registered bar-cell check =====
    tr_ok = report["segments"].get("TRAIN", {}).get("portfolio", {})
    val_ok = report["segments"].get("VAL", {}).get("portfolio", {})
    oos_ok = report["segments"].get("OOS1", {}).get("portfolio", {})
    checks = {
        "train_ci_gt0_and_ge005R_n:": bool(
            tr_ok and tr_ok["ci95"][0] > 0 and tr_ok["expectancy_r"] >= 0.05 and tr_ok["n_trades"] >= 500),
        "val_pos": bool(val_ok and val_ok["expectancy_r"] > 0),
        "oos1_pos_ci_gt0": bool(oos_ok and oos_ok["expectancy_r"] > 0 and oos_ok["ci95"][0] > 0),
    }
    checks["ALL_PASS"] = all(checks.values())
    report["bar_checks"] = checks
    logger.info(f"BAR-CHECKS: {checks}")
    out = DATA_DIR / "reports" / "w5b_entry_gated.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
