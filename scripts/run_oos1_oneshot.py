"""W3 — OOS1 ONE-SHOT (PLAN M5 mục 3: "chỉ chạy khi đã chốt") — cấu hình frozen:

Frozen config (không tuning sau VAL): H2b trigger × atrPct30d>0.70 tier, long, holding 48 bar,
horizon exit, SL thiên tai |MAE q05| TRAIN (recompute deterministic), governed sizing cap 3%
lev 1×, flat-EOD, funding thật, exit_maker=True (patience 12). Cả 2 kịch bản entry báo cáo;
kịch bản chính = maker/maker (RT ~0.036%, execution chiến thuật sẽ trade thật).

Protocol pre-registered TRƯỚC KHI CHẠY OOS1 (chạy ĐÚNG 1 LẦN, không iterate sau khi thấy):
- Judge: expectancy_r > 0 với CI95 (bootstrap) > 0, n ≥ 100 — trên PORTFOLIO OOS1.
- Kịch bản phụ (taker-entry) chỉ báo cáo minh bạch.
- KHÔNG chỉnh bất kỳ tham số nào sau khi thấy kết quả. FINAL OOS2 vẫn đóng băng.

Chạy: .venv/Scripts/python.exe scripts/run_oos1_oneshot.py
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
from solfut.research import events

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT"]
HOLDING = 48
OOS_START = pd.Timestamp("2024-07-01", tz="UTC")
OOS_END = pd.Timestamp("2025-08-31 23:59", tz="UTC")
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0


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


def atr_pct(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean().rolling(8640, min_periods=2880).rank(pct=True)


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    report: dict = {"segment": "OOS1_2024-07_2025-08", "protocol": "one-shot, pre-registered",
                    "symbols": {}, "entries": {}}
    all_trades: dict[str, list] = {"taker_worst": [], "maker_base": []}

    for sym in SYMBOLS:
        df = load_5m(sym)
        atrp = atr_pct(df)
        df_seg = df[(df.index >= OOS_START) & (df.index <= OOS_END + pd.Timedelta(days=2))]
        atrp_seg = atrp.loc[df_seg.index]
        mask = btc_jump_mask(df_seg.index) & atrp_seg.gt(0.70).fillna(False)
        ev_idx = df_seg.index[mask & (df_seg.index <= OOS_END)]

        # SL thiên tai: recompute trên TRAIN window (deterministic — cùng công thức, cùng data)
        df_train = df[(df.index >= pd.Timestamp("2020-10-01", tz="UTC"))
                      & (df.index <= pd.Timestamp("2023-06-30", tz="UTC") + pd.Timedelta(days=2))]
        atrp_tr = atrp.loc[df_train.index]
        mask_tr = btc_jump_mask(df_train.index) & atrp_tr.gt(0.70).fillna(False)
        ev_tr = df_train.index[mask_tr]
        mm = events.mfe_mae(df_train["close"], df_train["high"], df_train["low"], HOLDING)
        sl_dis = float(abs(mm.loc[ev_tr, "mae"].dropna().quantile(0.05)))

        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
            "entry_price": df_seg.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        funding = FundingSchedule.load(sym)
        sym_out = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis}
        for entry in ("taker_worst", "maker_base"):
            res = run_backtest(df_seg, sig, load_cost_model(), scenario=entry,
                               bound="sl_first", activity=None, funding=funding,
                               equity_start=50.0, sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                               lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                               exit_maker=True, exit_patience=12)
            m = compute_metrics(res.trades)
            sym_out[entry] = {"metrics": m, "engine_stats": res.stats}
            if len(res.trades):
                all_trades[entry].append(res.trades.assign(symbol=sym))
            logger.info(f"OOS1 {entry} {sym}: n={m.get('n_trades', 0)} "
                        f"expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                        f"PF={m.get('profit_factor_net', float('nan'))}")
        report["symbols"][sym] = sym_out

    for entry in ("taker_worst", "maker_base"):
        if not all_trades[entry]:
            report["entries"][entry] = {"n_trades": 0}
            continue
        tr = pd.concat(all_trades[entry], ignore_index=True).sort_values("exit_time")
        eq = 4 * 50.0 + tr["net_pnl"].cumsum()
        peak = np.maximum.accumulate(np.concatenate([[4 * 50.0], eq.values]))[1:]
        dd = float(((peak - eq.values) / peak * 100).max())
        r = tr["r_net"].to_numpy(float)
        lo, hi = bootstrap_expectancy_ci(r)
        pm = {
            "n_trades": int(len(tr)), "expectancy_r": float(np.nanmean(r)),
            "ci95": [lo, hi], "profit_factor_net":
                float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                      / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
                if (tr["net_pnl"] <= 0).any() else float("inf"),
            "max_dd_pct": dd, "equity_end": float(eq.iloc[-1]),
            "total_net_usdt": float(tr["net_pnl"].sum()),
            "win_rate": float((tr["net_pnl"] > 0).mean()),
        }
        pm["pass_protocol"] = bool(pm["n_trades"] >= 100 and lo > 0)
        report["entries"][entry] = {"metrics": pm}
        logger.info(f"OOS1 PORTFOLIO {entry}: n={pm['n_trades']} expR={pm['expectancy_r']:.4f} "
                    f"CI=[{lo:.4f},{hi:.4f}] PF={pm['profit_factor_net']:.2f} DD={dd:.1f}% "
                    f"net={pm['total_net_usdt']:.2f} USDT PASS={pm['pass_protocol']}")

    out = DATA_DIR / "reports" / "w3_oos1_oneshot.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
