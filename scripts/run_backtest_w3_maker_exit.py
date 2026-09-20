"""W3 — Ensemble 4 symbol (M4d portfolio) CHẠY LẠI với maker-exit.

KHÔNG phải hypothesis mới: cùng cấu hình pre-registered của M4d (H2b high-vol tier atrPct>0.70,
holding 48, SL thiên tai |MAE q05| TRAIN, governed + percent-risk) — chỉ nâng cấp EXECUTION
theo vòng 8 ("execution là biến số tối ưu hóa"): time/EOD exit đi bằng post-only limit
(trade-through, patience 12, fallback market; SL vẫn sống khi chờ). Gate settings.gates
KHÔNG ĐỔI. Kịch bản chính = maker/maker (RT ≈ 0.036%) kèm taker-entry/maker-exit để so.

Chạy: .venv/Scripts/python.exe scripts/run_backtest_w3_maker_exit.py
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
from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT"]
HOLDING = 48
T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START = pd.Timestamp("2023-07-01", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
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


def run_segment(specs: dict, contract_by_sym: dict, seg: str, s0: pd.Timestamp,
                s1: pd.Timestamp, entry_scenario: str) -> dict:
    out: dict = {"symbols": {}, "entry": entry_scenario, "segment": seg}
    all_trades = []
    for sym in SYMBOLS:
        try:
            df = load_5m(sym)
        except FileNotFoundError:
            logger.warning(f"{sym}: thiếu dữ liệu — bỏ qua")
            continue
        atrp = atr_pct(df)
        df = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
        atrp = atrp.loc[df.index]
        mask = btc_jump_mask(df.index) & atrp.gt(0.70).fillna(False)
        ev_idx = df.index[mask & (df.index >= s0) & (df.index <= s1)]

        mm = events.mfe_mae(df["close"], df["high"], df["low"], HOLDING)
        if seg.startswith("TRAIN"):
            sl_dis = float(abs(mm.loc[ev_idx, "mae"].dropna().quantile(0.05)))
            specs.setdefault(sym, {})["sl_disaster"] = sl_dis
        else:
            sl_dis = specs.get(sym, {}).get("sl_disaster")
        if not sl_dis:
            continue

        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
            "entry_price": df.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        funding = FundingSchedule.load(sym)
        res = run_backtest(df, sig, load_cost_model(), scenario=entry_scenario,
                           bound="sl_first", activity=None, funding=funding,
                           equity_start=50.0, sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                           lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                           exit_maker=True, exit_patience=12)
        m = compute_metrics(res.trades)
        out["symbols"][sym] = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis,
                               "metrics": m, "engine_stats": res.stats}
        if len(res.trades):
            all_trades.append(res.trades.assign(symbol=sym))
        logger.info(f"[{seg}/{entry_scenario}] {sym}: n={m.get('n_trades', 0)} "
                    f"expR={m.get('expectancy_r', float('nan')):.4f} "
                    f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                    f"costR={m.get('cost_r', float('nan')):.4f} "
                    f"exitMakerFill={res.stats.get('maker_exit_fill_rate')}")

    if not all_trades:
        out["portfolio"] = {"n_trades": 0}
        return out
    tr = pd.concat(all_trades, ignore_index=True).sort_values("exit_time")
    eq = 4 * 50.0 + tr["net_pnl"].cumsum()
    peak = np.maximum.accumulate(np.concatenate([[4 * 50.0], eq.values]))[1:]
    dd = float(((peak - eq.values) / peak * 100).max())
    r = tr["r_net"].to_numpy(float)
    lo, hi = bootstrap_expectancy_ci(r)
    pm = {
        "n_trades": int(len(tr)), "expectancy_r": float(np.nanmean(r)),
        "gross_expectancy_r": float(np.nanmean(tr["r_gross"])),
        "profit_factor_net": float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                                   / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
        if (tr["net_pnl"] <= 0).any() else float("inf"),
        "sqn_r": float(np.sqrt(len(r)) * np.nanmean(r) / np.nanstd(r, ddof=1)),
        "max_dd_pct": dd, "equity_end": float(eq.iloc[-1]),
        "expectancy_ci95": [lo, hi],
        "trades_per_year": float(len(tr) / max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)),
        "win_rate": float((tr["net_pnl"] > 0).mean()),
        "total_net_usdt": float(tr["net_pnl"].sum()),
        "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
    }
    pm["gates"] = gates_check(pm)
    out["portfolio"] = {"metrics": pm}
    logger.info(f"[{seg}/{entry_scenario}] PORTFOLIO: n={pm['n_trades']} expR={pm['expectancy_r']:.4f} "
                f"CI=[{lo:.4f},{hi:.4f}] PF={pm['profit_factor_net']:.2f} SQN={pm['sqn_r']:.2f} "
                f"DD={dd:.1f}% net={pm['total_net_usdt']:.2f} USDT ALL_PASS={pm['gates']['ALL_PASS']['ok']}")
    return out


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    report: dict = {"config": {"holding": HOLDING, "risk_cap_pct": RISK_CAP_PCT,
                               "exit_maker": True, "exit_patience": 12,
                               "note": "cùng cấu hình pre-registered M4d — chỉ nâng execution"},
                    "train": {}, "val": {}}
    specs_train = {}
    for entry in ("taker_worst", "maker_base"):
        specs_train[entry] = {}
        report["train"][entry] = run_segment(specs_train[entry], contract_by_sym, "TRAIN",
                                             T_START, T_END, entry)
    for entry in ("taker_worst", "maker_base"):
        report["val"][entry] = run_segment(specs_train[entry], contract_by_sym, "VAL",
                                           V_START, V_END, entry)

    out = DATA_DIR / "reports" / "w3_maker_exit.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
