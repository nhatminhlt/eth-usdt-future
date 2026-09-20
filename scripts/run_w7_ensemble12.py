"""W7 — Consolidation trước khi tiêu vé OOS2 (option 2):

(1) Replicate H2b×tier trên 4 symbol MỚI (ATOM/DOT/LTC/EOS) — event-study pre-registered
    (segment ledger mới theo symbol, criteria giống hệt H2b gốc), CASUAL measure.
(2) Ensemble-12 (8 cũ + 4 mới) cùng cấu hình FROZEN: TRAIN/VAL/OOS1 đánh giá lại tại entry
    (governed, maker/maker, tier atrRank>0.70 — CHƯA gate ATR≥0.8 ở tầng full-ensemble;
     phân bậc vol vẫn giữ làm attribution).
(3) Nếu ensemble-12 TRAIN CI>0 & VAL/OOS1 dương và IBS/ATR≥0.8-cut tiếp tục dương cả 3 segment
    → cấu hình OOS2 lên cấp (báo cáo cho user bốc vé).

Pre-registers: 4 hàng H2b_seesaw_long_<SYM> (q.criteria M2.5) + 1 hàng
W7_ensemble12_stress_gated (criteria: TRAIN CI>0+ex≥0.05R n≥500 + VAL>0 + OOS1>0).

Chạy: .venv/Scripts/python.exe scripts/run_w7_ensemble12.py
Output: data/reports/w7_ensemble12.json
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
from solfut.research import events, hypotheses as hl

SYMBOLS = [
    "SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT",
    "ATOMUSDT", "DOTUSDT", "LTCUSDT",
]
HOLDING = 48
SEGMENTS = {
    "TRAIN": (pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")),
    "VAL": (pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-06-30 23:59", tz="UTC")),
    "OOS1": (pd.Timestamp("2024-07-01", tz="UTC"), pd.Timestamp("2025-08-31 23:59", tz="UTC")),
}
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0
CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}   # H2b criteria gốc


def load_5m(symbol: str) -> pd.DataFrame | None:
    try:
        df = load_monthlies(symbol, "5m")
    except FileNotFoundError:
        return None
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


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    # ===== (1) replication event-study 4 symbol mới =====
    for sym in SYMBOLS[8:]:
        df = load_5m(sym)
        if df is None:
            logger.warning(f"{sym}: chưa tải — skip replication")
            continue
        seg = f"TRAIN_2020-10_2023-06_{sym}"
        hid = f"H2b_seesaw_long_{sym}"
        hl.register(hid=hid,
                    name=f"{hid} — replication trên {sym}, định nghĩa GIỐNG HỆT bản SOL",
                    source="W7 expansion (user: thêm chứng cứ trước khi tiêu OOS2)",
                    criteria=dict(CRITERIA), segment=seg)
        df_tr = df[(df.index >= SEGMENTS["TRAIN"][0]) & (df.index <= SEGMENTS["TRAIN"][1])]
        mask = btc_jump_mask(df_tr.index)
        res = events.run_event_study(df_tr, mask, hid)
        ex1 = res.excess_by_horizon.get("+1h")
        t1 = res.t_by_horizon.get("+1h")
        ci1 = res.ci_event_by_horizon.get("+1h", {})
        lo1 = ci1.get("lo")
        ok = bool(ex1 == ex1 and ex1 >= 0.0005 and t1 == t1 and t1 >= 2.0
                  and lo1 == lo1 and lo1 is not None and lo1 > 0)
        result = {"n_events": int(res.n_events),
                  "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
                  "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
                  "ci95_1h": [lo1, ci1.get("hi")]}
        hl.record_verdict(hid, "pass" if ok else "kill", result)
        logger.info(f"REPL {hid}: n={res.n_events} ex@1h={ex1*100:+.3f}% t={t1:.2f} → "
                    f"{'pass' if ok else 'kill'}")

    # ===== (2) ensemble-12 đánh giá 3 segment =====
    hl.register(hid="W7_ensemble12_stress_checked",
                name="W7 ensemble-12 (8 cũ + ATOM/DOT/LTC = 11; EOS delisted — loại) — cùng cấu hình frozen; "
                     "pre-check trước khi tiêu vé OOS2",
                source="W5 stress-gated + W7 expansion",
                criteria={"train": "CI95 lo>0 & expectancy ≥ 0.05R & n≥500",
                          "val": "expectancy > 0", "oos1": "expectancy > 0"},
                segment="WAVE3_2020-10_2025-08")

    report: dict = {"symbols": SYMBOLS, "segments": {}, "by_symbol": {}}
    sl_by_sym: dict = {}
    for seg, (s0, s1) in SEGMENTS.items():
        all_tr = []
        for sym in SYMBOLS:
            df = load_5m(sym)
            if df is None:
                continue
            atr_abs = abs_atr_pct(df)
            atr_rank = atr_abs.rolling(8640, min_periods=2880).rank(pct=True)
            df_seg = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
            rank_seg = atr_rank.loc[df_seg.index]
            mask_evt = btc_jump_mask(df_seg.index) & rank_seg.gt(0.70).fillna(False)
            ev_idx = df_seg.index[mask_evt & (df_seg.index <= s1)]
            # entry-gate stress: ATR tuyệt đối ≥ 0.80% (frozen từ W5)
            ev_idx = ev_idx[atr_abs.loc[ev_idx] >= 0.80]

            if seg == "TRAIN" and sym not in sl_by_sym:
                df_tr_full = df[(df.index >= SEGMENTS["TRAIN"][0])
                                & (df.index <= SEGMENTS["TRAIN"][1] + pd.Timedelta(days=2))]
                rank_tr = atr_rank.loc[df_tr_full.index]
                mask_tr = btc_jump_mask(df_tr_full.index) & rank_tr.gt(0.70).fillna(False)
                ev_tr = df_tr_full.index[mask_tr]
                ev_tr = ev_tr[atr_abs.loc[ev_tr] >= 0.80]
                mm = events.mfe_mae(df_tr_full["close"], df_tr_full["high"], df_tr_full["low"], HOLDING)
                sl_by_sym[sym] = float(abs(mm.loc[ev_tr, "mae"].dropna().quantile(0.05)))
            sl_dis = sl_by_sym.get(sym)
            if not sl_dis or sl_dis != sl_dis:
                logger.warning(f"{sym}: SL n/a — skip")
                continue

            sig = pd.DataFrame({
                "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
                "entry_price": df_seg.loc[ev_idx, "close"].values,
                "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
            })
            funding = FundingSchedule.load(sym) if (DATA_DIR / "funding" / f"{sym}_funding.parquet").exists() else None
            res = run_backtest(df_seg, sig, load_cost_model(), scenario="maker_base",
                               bound="sl_first", activity=None, funding=funding,
                               equity_start=50.0, sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                               lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                               exit_maker=True, exit_patience=12)
            if len(res.trades):
                all_tr.append(res.trades.assign(symbol=sym))
                report["by_symbol"].setdefault(sym, {})[seg] = {
                    "n": int(len(res.trades)), "expectancy_r": float(res.trades["r_net"].mean())}
            logger.info(f"[{seg}] {sym}: trades={m if (m:=len(res.trades)) else 0} "
                        f"expR={float(res.trades['r_net'].mean()) if len(res.trades) else float('nan'):.4f}")
        if all_tr:
            tr = pd.concat(all_tr, ignore_index=True).sort_values("exit_time")
            n_pockets = len(tr["symbol"].unique())
            eq = n_pockets * 50.0 + tr["net_pnl"].cumsum()
            peak = np.maximum.accumulate(np.concatenate([[n_pockets * 50.0], eq.values]))[1:]
            dd = float(((peak - eq.values) / peak * 100).max())
            r = tr["r_net"].to_numpy(float)
            lo, hi = bootstrap_expectancy_ci(r)
            span_years = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
            pm = {
                "n_trades": int(len(tr)), "expectancy_r": float(np.nanmean(r)),
                "gross_expectancy_r": float(np.nanmean(tr["r_gross"])), "ci95": [lo, hi],
                "profit_factor_net": float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                                           / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
                if (tr["net_pnl"] <= 0).any() else float("inf"),
                "sqn_r": float(np.sqrt(len(r)) * np.nanmean(r) / np.nanstd(r, ddof=1)),
                "max_dd_pct": dd, "total_net_usdt": float(tr["net_pnl"].sum()),
                "win_rate": float((tr["net_pnl"] > 0).mean()),
                "trades_per_year": float(len(tr) / span_years),
            }
            if seg == "TRAIN":
                pm["gates"] = gates_check(pm)
            report["segments"][seg] = {"portfolio": pm}
            logger.info(f"[{seg}] ENSEMBLE-12 (stress-gated): n={pm['n_trades']} "
                        f"expR={pm['expectancy_r']:.4f} CI=[{lo:.4f},{hi:.4f}] "
                        f"PF={pm['profit_factor_net']:.2f} DD={dd:.1f}% net={pm['total_net_usdt']:.2f}")

    # chấm config pre-registered
    tr = report["segments"].get("TRAIN", {}).get("portfolio", {})
    val = report["segments"].get("VAL", {}).get("portfolio", {})
    oos = report["segments"].get("OOS1", {}).get("portfolio", {})
    checks = {
        "train": bool(tr and tr["ci95"][0] > 0 and tr["expectancy_r"] >= 0.05 and tr["n_trades"] >= 500),
        "val_pos": bool(val and val["expectancy_r"] > 0),
        "oos1_pos": bool(oos and oos["expectancy_r"] > 0),
    }
    checks["READY_FOR_OOS2"] = all(checks.values())
    report["checks"] = checks
    hl.record_verdict("W7_ensemble12_stress_checked",
                      "ready" if checks["READY_FOR_OOS2"] else ("kill" if not checks["train"] else "not_ready"),
                      {"checks": checks,
                       "train": {k: tr.get(k) for k in ("n_trades", "expectancy_r", "ci95")},
                       "val_expectancy_r": val.get("expectancy_r"),
                       "oos1_expectancy_r": oos.get("expectancy_r")})
    logger.info(f"CHECKS: {checks}")

    out = DATA_DIR / "reports" / "w7_ensemble12.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
