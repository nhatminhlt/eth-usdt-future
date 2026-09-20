"""OOS2 ONE-SHOT — ĐẠI BÁNG CUỐI cho lớp stress-fade (pre-registered `W5_stress_gated_ensemble8_OOS2`, pending).

Cấu hình FROZEN — giống hệt W5b entry-gated (đã đo TRAIN/VAL/OOS1):
- Universe 8: SOL/ETH/DOGE/AVAX/BNB/XRP/ADA/LINK (ETH/LTC minNotional 20 USDT — per-symbol contract).
- Trigger: BTC 5m ret ≤ −2σ(96) × atrRank30d > 0.70 × ATR14-5m TUYỆT ĐỐI ≥ 0.80% (entry gate).
- Long tại close event bar; holding 48 bar; TP KHÔNG; SL thiên tai = |MAE q05| TRAIN per-symbol
  (derive trên event set ĐÃ GATE — giống W5b, deterministic recompute).
- Governed sizing: notional = max(minNotional, min(equity×1×, equity×3%/sl)); maker/maker
  (exit post-only trade-through, patience 12); flat-EOD; funding theo parquet có sẵn
  (SOL/ETH/DOGE/AVAX; 4 còn lại không có parquet → funding=0 — GIỐNG HỆT W5b, không đổi config).
- Kịch bản chính: maker_base; taker_worst báo cáo minh bạch.

TIÊU CHÍ (đăng ký TRƯỚC — ledger): expectancy_r > 0 VÀ CI95 lo > 0 VÀ n ≥ 100 trên PORTFOLIO
maker_base. PASS → ứng viên edge; FAIL → NO-GO chốt lớp (không re-run, không chỉnh tiêu chí).

Chạy: .venv/Scripts/python.exe scripts/run_oos2_oneshot.py  — CHẠY ĐÚNG MỘT LẦN.
Output: data/reports/oos2_oneshot.json
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
from solfut.backtest.metrics import bootstrap_expectancy_ci, compute_metrics
from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events, hypotheses as hl

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
HOLDING = 48
OOS_START = pd.Timestamp("2025-09-01", tz="UTC")
OOS_END = pd.Timestamp("2026-08-31 23:59", tz="UTC")
TRAIN_START = pd.Timestamp("2020-10-01", tz="UTC")
TRAIN_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0
ATR_GATE = 0.80
HID = "W5_stress_gated_ensemble8_OOS2"


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
    tr = pd.concat([df[".high"] - df["low"] if False else df["high"] - df["low"],
                    (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return (tr.rolling(14).mean() / df["close"] * 100)


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")
                       and s in SYMBOLS}

    report: dict = {"segment": "OOS2_2025-09_2026-08", "one_shot": True,
                    "config": "frozen W5b ensemble-8 stress-gated", "symbols": {}, "entries": {}}
    all_trades: dict[str, list] = {"maker_base": [], "taker_worst": []}

    for sym in SYMBOLS:
        df = load_5m(sym)
        if df is None:
            logger.warning(f"{sym}: thiếu dữ liệu — bỏ")
            continue
        atr_abs = abs_atr_pct(df)
        atr_rank = atr_abs.rolling(8640, min_periods=2880).rank(pct=True)

        # SL derive từ TRAIN (deterministic, gate giống W5b)
        df_tr = df[(df.index >= TRAIN_START) & (df.index <= TRAIN_END + pd.Timedelta(days=2))]
        atr_abs_tr = atr_abs.loc[df_tr.index]
        rank_tr = atr_rank.loc[df_tr.index]
        mask_tr = btc_jump_mask(df_tr.index) & rank_tr.gt(0.70).fillna(False)
        ev_tr = df_tr.index[mask_tr]
        ev_tr = ev_tr[atr_abs_tr.loc[ev_tr] >= ATR_GATE]
        mm = events.mfe_mae(df_tr["close"], df_tr["high"], df_tr["low"], HOLDING)
        sl_dis = float(abs(mm.loc[ev_tr, "mae"].dropna().quantile(0.05)))

        df_seg = df[(df.index >= OOS_START) & (df.index <= OOS_END + pd.Timedelta(days=2))]
        atr_abs_seg = atr_abs.loc[df_seg.index]
        rank_seg = atr_rank.loc[df_seg.index]
        mask_seg = btc_jump_mask(df_seg.index) & rank_seg.gt(0.70).fillna(False)
        ev_idx = df_seg.index[mask_seg & (df_seg.index <= OOS_END)]
        ev_idx = ev_idx[atr_abs_seg.loc[ev_idx] >= ATR_GATE]

        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
            "entry_price": df_seg.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        funding = FundingSchedule.load(sym)      # tự rỗng nếu thiếu parquet — như W5b
        sym_out = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis, "runs": {}}
        for entry in ("maker_base", "taker_worst"):
            res = run_backtest(df_seg, sig, load_cost_model(), scenario=entry,
                               bound="sl_first", activity=None, funding=funding,
                               equity_start=50.0, sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                               lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                               exit_maker=True, exit_patience=12)
            m = compute_metrics(res.trades)
            sym_out["runs"][entry] = {"metrics": m, "engine_stats": res.stats}
            if len(res.trades):
                all_trades[entry].append(res.trades.assign(symbol=sym))
            logger.info(f"OOS2/{entry} {sym}: events={len(ev_idx)} trades={m.get('n_trades', 0)} "
                        f"expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                        f"PF={m.get('profit_factor_net', float('nan'))} sl={sl_dis:.3f}")
        report["symbols"][sym] = sym_out

    for entry in ("maker_base", "taker_worst"):
        if not all_trades[entry]:
            report["entries"][entry] = {"n_trades": 0}
            continue
        tr = pd.concat(all_trades[entry], ignore_index=True).sort_values("exit_time")
        n_pockets = len(tr["symbol"].unique())
        eq = n_pockets * 50.0 + tr["net_pnl"].cumsum()
        peak = np.maximum.accumulate(np.concatenate([[n_pockets * 50.0], eq.values]))[1:]
        dd = float(((peak - eq.values) / peak * 100).max())
        r = tr["r_net"].to_numpy(float)
        lo, hi = bootstrap_expectancy_ci(r)
        span_years = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
        pm = {
            "n_trades": int(len(tr)),
            "expectancy_r": float(np.nanmean(r)),
            "ci95": [lo, hi],
            "profit_factor_net": float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                                       / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
            if (tr["net_pnl"] <= 0).any() else float("inf"),
            "sqn_r": float(np.sqrt(len(r)) * np.nanmean(r) / np.nanstd(r, ddof=1)),
            "max_dd_pct": dd, "equity_end": float(eq.iloc[-1]),
            "total_net_usdt": float(tr["net_pnl"].sum()),
            "win_rate": float((tr["net_pnl"] > 0).mean()),
            "trades_per_year": float(len(tr) / span_years),
            "by_symbol_expectancy": tr.groupby("symbol")["r_net"].mean().round(4).to_dict(),
        }
        pm["pass_criteria"] = bool(pm["n_trades"] >= 100 and pm["expectancy_r"] > 0
                                   and lo == lo and lo > 0)
        report["entries"][entry] = {"metrics": pm}
        logger.info(f"OOS2 PORTFOLIO ({entry}): n={pm['n_trades']} expR={pm['expectancy_r']:.4f} "
                    f"CI=[{lo:.4f},{hi:.4f}] PF={pm['profit_factor_net']:.2f} DD={dd:.1f}% "
                    f"net={pm['total_net_usdt']:.2f} USDT PASS={pm['pass_criteria']}")

    # ===== chấm theo tiêu chí pre-registered (maker_base là kịch bản chính) =====
    main_m = report["entries"]["maker_base"]["metrics"]
    verdict = "pass" if main_m.get("pass_criteria") else "kill"
    hl.record_verdict(HID, verdict, {
        "oos2": {k: main_m.get(k) for k in ("n_trades", "expectancy_r", "ci95",
                                            "profit_factor_net", "max_dd_pct",
                                            "total_net_usdt", "win_rate", "by_symbol_expectancy")},
        "taker_worst_expectancy_r": report["entries"].get("taker_worst", {})
        .get("metrics", {}).get("expectancy_r"),
        "criteria": "expectancy>0 & CI95lo>0 & n>=100 (maker_base portfolio)",
    })
    report["verdict"] = verdict
    out = DATA_DIR / "reports" / "oos2_oneshot.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"**** OOS2 VERDICT: {verdict.upper()} ****")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
