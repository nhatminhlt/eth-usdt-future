"""W3 FINAL — Ensemble 8 symbol (mọi symbol H2b replicate: SOL/ETH/DOGE/AVAX/BNB/XRP/ADA/LINK),
cấu hình frozen của M4d/W3 (tier atrPct>0.70, holding 48, horizon exit, SL thiên tai |MAE q05|
TRAIN, governed cap 3% lev 1×, exit_maker, patience 12), đánh giá TUẦN TỰ TRAIN→VAL→OOS1.

Pre-registered (TRƯỚC KHI CHẠY — segment WAVE3):
- Gate TRAIN: settings.gates trên portfolio (gross>0, net≥0.05R, CI>0, PF≥1.3, SQN≥2, n≥100, DD≤25%).
- Gate VAL: expectancy_r > 0.
- Gate OOS1: expectancy_r > 0 với CI95 > 0, n ≥ 100 — ONE SHOT, không iterate sau khi thấy.
- Kịch bản chính: maker/maker. taker-entry báo cáo minh bạch.
KILL nếu fail ở bất kỳ cổng. FINAL OOS2 vẫn đóng băng.

Chạy: .venv/Scripts/python.exe scripts/run_w3_ensemble8.py
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

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
HOLDING = 48
SEGMENTS = {
    "TRAIN": (pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")),
    "VAL": (pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-06-30 23:59", tz="UTC")),
    "OOS1": (pd.Timestamp("2024-07-01", tz="UTC"), pd.Timestamp("2025-08-31 23:59", tz="UTC")),
}
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0
HID = "H2bHV_ensemble8"


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


def portfolio_metrics(tr: pd.DataFrame, n_pockets: float) -> dict:
    eq = n_pockets * 50.0 + tr["net_pnl"].cumsum()
    peak = np.maximum.accumulate(np.concatenate([[n_pockets * 50.0], eq.values]))[1:]
    dd = float(((peak - eq.values) / peak * 100).max())
    r = tr["r_net"].to_numpy(float)
    lo, hi = bootstrap_expectancy_ci(r)
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
        "trades_per_year": float(len(tr) / max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)),
        "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
    }


def main() -> None:
    hl.register(hid=HID,
                name=f"{HID}: ensemble 8 symbol H2b×tier, maker/maker, governed — "
                     "chuỗi cổng TRAIN→VAL→OOS1, mỗi OOS1 một phát duy nhất",
                source="H2b replicate 8/8 symbol (ledger); cấu trúc frozen từ M4d/W3",
                criteria={"train": "settings.gates portfolio", "val": "expectancy>0",
                          "oos1": "expectancy>0 & CI95>0 & n>=100"},
                segment="WAVE3_2020-10_2025-08")

    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    report: dict = {"hid": HID, "symbols": SYMBOLS, "segments": {}}
    sl_by_sym: dict = {}
    for entry in ("maker_base", "taker_worst"):      # maker/maker = kịch bản chính, chạy trước
        seg_trades = {}
        for seg, (s0, s1) in SEGMENTS.items():
            all_tr = []
            for sym in SYMBOLS:
                try:
                    df = load_5m(sym)
                except FileNotFoundError:
                    logger.warning(f"{sym}: thiếu dữ liệu — bỏ qua")
                    continue
                atrp = atr_pct(df)
                df_seg = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
                atrp_seg = atrp.loc[df_seg.index]
                mask = btc_jump_mask(df_seg.index) & atrp_seg.gt(0.70).fillna(False)
                ev_idx = df_seg.index[mask & (df_seg.index <= s1)]

                if seg == "TRAIN" and sym not in sl_by_sym:
                    df_tr = df[(df.index >= SEGMENTS["TRAIN"][0])
                               & (df.index <= SEGMENTS["TRAIN"][1] + pd.Timedelta(days=2))]
                    atrp_tr = atrp.loc[df_tr.index]
                    mask_tr = btc_jump_mask(df_tr.index) & atrp_tr.gt(0.70).fillna(False)
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
                res = run_backtest(df_seg, sig, load_cost_model(), scenario=entry,
                                   bound="sl_first", activity=None,
                                   funding=FundingSchedule.load(sym), equity_start=50.0,
                                   sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                                   lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                                   exit_maker=True, exit_patience=12)
                if len(res.trades):
                    all_tr.append(res.trades.assign(symbol=sym))
            if all_tr:
                tr = pd.concat(all_tr, ignore_index=True).sort_values("exit_time")
                seg_trades[seg] = tr
                pm = portfolio_metrics(tr, len(SYMBOLS))
                if seg == "TRAIN":
                    pm["gates"] = gates_check(pm)
                if seg == "OOS1":
                    pm["pass_oos1"] = bool(pm["n_trades"] >= 100 and pm["ci95"][0] > 0)
                report["segments"].setdefault(seg, {})[entry] = {"portfolio": pm}
                logger.info(f"[{seg}/{entry}] PORTFOLIO-8: n={pm['n_trades']} expR={pm['expectancy_r']:.4f} "
                            f"CI=[{pm['ci95'][0]:.4f},{pm['ci95'][1]:.4f}] PF={pm['profit_factor_net']:.2f} "
                            f"DD={pm['max_dd_pct']:.1f}% net={pm['total_net_usdt']:.2f}")

        # chấm chuỗi cổng theo kịch bản chính (maker_base)
        if entry == "maker_base":
            tr_ok = report["segments"]["TRAIN"][entry]["portfolio"].get("gates", {}).get("ALL_PASS", {}).get("ok")
            val_exp = report["segments"]["VAL"][entry]["portfolio"]["expectancy_r"]
            oos = report["segments"]["OOS1"][entry]["portfolio"]
            oos_ok = oos.get("pass_oos1", False)
            verdict = "pass" if (tr_ok and val_exp > 0 and oos_ok) else "kill"
            hl.record_verdict(HID, verdict, {
                "train_all_pass": tr_ok,
                "val_expectancy_r": val_exp,
                "oos1_expectancy_r": oos["expectancy_r"], "oos1_ci95": oos["ci95"],
                "oos1_pass": oos_ok,
            })
            report["verdict"] = verdict
            logger.info(f"VERDICT {HID}: {verdict} (train={tr_ok} val={val_exp:.4f} oos1_pass={oos_ok})")

    out = DATA_DIR / "reports" / "w3_ensemble8.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
