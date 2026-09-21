"""W9b-DIAGNOSTIC — implementation cho atom fade pass-drift cross-asset: BTC H10b, BTC H12,
ETH H12 (SOL đã đo đầy đủ ở W6; H10b SOL + H12 SOL đã KILL implementation từ trước).

KHÔNG PHẢI ỨNG VIÊN: lớp fade đã NO-GO OOS2 (regime decay 2025-26); không còn holdout sạch.
Diagnostic chỉ định lượng gross→net sau phí thật trên BTC/ETH TRAIN/VAL.

Cấu hình: frame 5m; holding 12 bar (+1h); taker entry tại close trigger; maker đối chiếu;
SL derive TRAIN: q05 (horizon-class) + q25 (bracket-class); percent_risk 1%/5× và governed
3%/1×; funding ETH parquet có thật; BTC không có → 0 (underestimate nhẹ).

Chạy: .venv/Scripts/python.exe scripts/run_w9b_impl_diagnostic.py
Output: data/reports/w9b_impl_diagnostic.json
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
from solfut.backtest.metrics import compute_metrics
from solfut.data.downloader import DATA_DIR
from solfut.research import events

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HOLDING = 12
CASES = [("BTCUSDT", "H10b"), ("BTCUSDT", "H12"), ("ETHUSDT", "H12")]
CONTRACTS = {"BTCUSDT": {"lot_step": 0.001, "min_qty": 0.001, "min_notional": 50.0, "leverage_cap": 5},
             "ETHUSDT": {"lot_step": 0.001, "min_qty": 0.001, "min_notional": 20.0, "leverage_cap": 5}}


def session_vwap(df: pd.DataFrame) -> pd.Series:
    day = df.index.floor("D")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv / vv


def mask_for(sym: str, atom: str, m5: pd.DataFrame) -> pd.Series:
    c, l, vol = m5["close"], m5["low"], m5["volume"]
    if atom == "H10b":
        low48 = l.rolling(48).min().shift(1)
        vol_sma48 = vol.rolling(48).mean().shift(1)
        return ((c < low48) & (vol > 1.5 * vol_sma48)).fillna(False)
    vwap = session_vwap(m5)
    dev = (c - vwap) / c
    z12 = dev / dev.rolling(8640, min_periods=2880).std()
    return z12.le(-2).fillna(False)


def main() -> None:
    cost = load_cost_model()
    report: dict = {"note": "DIAGNOSTIC — fade atoms pass-drift on BTC/ETH; not candidates (fade class NO-GO OOS2)"}
    for sym, atom in CASES:
        m5 = pd.read_parquet(DATA_DIR / f"{sym}_5m_enriched.parquet").sort_index()
        m5 = m5[m5.index <= V_END + pd.Timedelta(days=3)]
        mask = mask_for(sym, atom, m5)
        tr_m = mask & (m5.index >= T_START) & (m5.index <= T_END)
        ev = m5.index[tr_m]
        mm = events.mfe_mae(m5["close"], m5["high"], m5["low"], HOLDING)
        sl_q05 = float((-mm.loc[ev, "mae"]).dropna().quantile(0.05))
        sl_q25 = float((-mm.loc[ev, "mae"]).dropna().quantile(0.25))
        funding = FundingSchedule.load(sym)   # BTC → rỗng (0)
        contract = CONTRACTS[sym]
        report[f"{atom}_{sym}"] = {"sl_q05": sl_q05, "sl_q25": sl_q25, "n_train_events": int(len(ev)),
                                   "funding": "parquet" if len(funding.rates) else "none(0)", "segments": {}}
        logger.info(f"{atom}_{sym}: events={len(ev)} SL q05={sl_q05:.4f} q25={sl_q25:.4f}")
        for seg, (s, e) in {"TRAIN": (T_START, T_END), "VAL": (T_END, V_END)}.items():
            seg_m = mask & (m5.index > (T_END if seg == "VAL" else T_START - pd.Timedelta(days=2))) \
                    & (m5.index <= e + pd.Timedelta(days=2))
            ev_idx = m5.index[seg_m & (m5.index <= e)]
            runs = {}
            for sl_name, sl_pct, sizing, lev in (("q05_pctrisk", sl_q05, "percent_risk", 5.0),
                                                 ("q25_pctrisk", sl_q25, "percent_risk", 5.0),
                                                 ("q05_governed", sl_q05, "governed", 1.0)):
                sig = pd.DataFrame({
                    "entry_time": ev_idx, "sid": f"{atom}{sym}", "direction": 1,
                    "entry_price": m5.loc[ev_idx, "close"].values,
                    "sl_pct": sl_pct, "tp_pct": np.nan, "holding_bars": HOLDING,
                })
                df_seg = m5[(m5.index >= (T_START if seg == "TRAIN" else T_END)) & (m5.index <= e + pd.Timedelta(days=3))]
                for scenario in ("taker_worst", "maker_base"):
                    res = run_backtest(df_seg, sig, cost, scenario=scenario, bound="sl_first",
                                       activity=None, patience_bars=12, funding=funding,
                                       equity_start=50.0, sizing=sizing, risk_cap_pct=3.0,
                                       lev_cap_eff=lev, contract=contract)
                    m = compute_metrics(res.trades)
                    runs[f"{sl_name}/{scenario}"] = {"metrics": m, "engine_stats": res.stats}
                    logger.info(f"{atom}_{sym}/{seg}/{sl_name}/{scenario}: n={m.get('n_trades', 0)} "
                                f"grossR={m.get('gross_expectancy_r', float('nan')):+.4f} "
                                f"netR={m.get('expectancy_r', float('nan')):+.4f} "
                                f"costR={m.get('cost_r', float('nan')):.4f} "
                                f"PF={m.get('profit_factor_net', float('nan')):.3f}")
            report[f"{atom}_{sym}"]["segments"][seg] = runs

    out = DATA_DIR / "reports" / "w9b_impl_diagnostic.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
