"""W9c-DIAGNOSTIC — implementation cho atom MTF DUY NHẤT pass drift: W9c3_mtf_macd_break_long_BTCUSDT
(D1 bull(EMA200, prev-day) & MACD-hist(H4, bar đã đóng) > 0 & H1 close phá đỉnh 20 bar).

KHÔNG PHẢI ỨNG VIÊN GO-LIVE: 1/24 atom pass — tần suất này nhất quán với may mắn multiple-testing;
không còn holdout sạch (OOS1/OOS2 đã tiêu). Diagnostic trả lời: gross→net sau phí thật trên
engine + governed sizing; BTC minNotional 50 USDT (exchangeInfo 2026-09-21) với $50 equity.

Cấu hình: frame H1; taker entry tại close trigger (đúng phép đo drift); maker post-only
đối chiếu; horizon-exit holding 4 bar; SL thiên tai = |MAE q05| TRAIN (derive deterministic);
KHÔNG TP. Governed sizing (risk_cap 3%, lev_eff 1). Funding BTC KHÔNG có parquet → 0
(underestimate nhẹ — BTC funding dương phần lớn lịch sử, bất lợi cho long).

Chạy: .venv/Scripts/python.exe scripts/run_w9c_impl_diagnostic.py
Output: data/reports/w9c_impl_diagnostic.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.backtest.costs import load_cost_model
from solfut.backtest.engine import run_backtest
from solfut.backtest.metrics import compute_metrics, gates_check
from solfut.data.downloader import DATA_DIR
from solfut.data.resample import resample
from solfut.features.indicators import ema, macd
from solfut.research import events

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HOLDING = 4
SYM = "BTCUSDT"
CONTRACT = {"lot_step": 0.001, "min_qty": 0.001, "min_notional": 50.0, "leverage_cap": 5}


def dprev(s: pd.Series, trigger_idx: pd.DatetimeIndex) -> pd.Series:
    key = trigger_idx.floor("D") - pd.Timedelta(days=1)
    return pd.Series(s.reindex(key).values, index=trigger_idx)


def hprev(s: pd.Series, trigger_idx: pd.DatetimeIndex) -> pd.Series:
    key = trigger_idx.floor("4h") - pd.Timedelta(hours=4)
    return pd.Series(s.reindex(key).values, index=trigger_idx)


def main() -> None:
    m5 = pd.read_parquet(DATA_DIR / f"{SYM}_5m_enriched.parquet").sort_index()
    m5 = m5[m5.index <= V_END + pd.Timedelta(days=3)]
    h1 = resample(m5, "1h")
    h4 = resample(m5, "4h")
    d1 = resample(m5, "1D")

    d1_bull_day = d1["close"] > ema(d1["close"], 200)
    h4_hist = macd(h4["close"])["hist"]
    idx = h1.index
    bull = dprev(d1_bull_day, idx).fillna(False)
    hist_prev = hprev(h4_hist, idx)
    c1 = h1["close"]
    hh20 = c1.rolling(20, min_periods=20).max().shift(1)
    mask = (bull & (hist_prev > 0) & (c1 >= hh20)).fillna(False)

    # derive SL từ TRAIN (deterministic, long) — 2 biến thể: q05 (horizon-class) & q25 (bracket-class)
    tr_m = mask & (h1.index >= T_START) & (h1.index <= T_END)
    ev = h1.index[tr_m]
    mm = events.mfe_mae(h1["close"], h1["high"], h1["low"], HOLDING)
    sl_q05 = float((-mm.loc[ev, "mae"]).dropna().quantile(0.05))
    sl_q25 = float((-mm.loc[ev, "mae"]).dropna().quantile(0.25))
    logger.info(f"{SYM} W9c3-macd-break-long: events TRAIN={len(ev)}, SL q05={sl_q05:.4f} q25={sl_q25:.4f}")

    cost = load_cost_model()
    report: dict = {"hid": "W9c3_mtf_macd_break_long_BTCUSDT", "note": "DIAGNOSTIC — not a candidate; no clean holdout",
                    "sl_q05": sl_q05, "sl_q25": sl_q25, "holding_bars": HOLDING,
                    "contract": CONTRACT, "funding": "none (BTC parquet thiếu) → underestimate chi phí long",
                    "walls": "governed lev1×: lot 0.001 BTC × giá <$50k < minNotional 50 → 0 lệnh khả thi "
                             "(cấu trúc sàn, không phải chiến lược); percent_risk 1%/5× mới khả thi",
                    "segments": {}}
    for seg, (s, e) in {"TRAIN": (T_START, T_END), "VAL": (T_END, V_END)}.items():
        seg_m = mask & (h1.index > (T_END if seg == "VAL" else T_START - pd.Timedelta(days=2))) \
                & (h1.index <= e + pd.Timedelta(days=2))
        ev_idx = h1.index[seg_m & (h1.index <= e)]
        runs = {}
        for sl_name, sl_pct, sizing in (("q05_governed", sl_q05, "governed"),
                                        ("q05_pctrisk", sl_q05, "percent_risk"),
                                        ("q25_pctrisk", sl_q25, "percent_risk")):
            sig = pd.DataFrame({
                "entry_time": ev_idx, "sid": "W9c3diag", "direction": 1,
                "entry_price": h1.loc[ev_idx, "close"].values,
                "sl_pct": sl_pct, "tp_pct": np.nan, "holding_bars": HOLDING,
            })
            h1_seg = h1[(h1.index >= (T_START if seg == "TRAIN" else T_END)) & (h1.index <= e + pd.Timedelta(days=3))]
            for scenario in ("taker_worst", "maker_base"):
                res = run_backtest(h1_seg, sig, cost, scenario=scenario, bound="sl_first",
                                   activity=None, patience_bars=4, funding=None,
                                   equity_start=50.0, sizing=sizing, risk_cap_pct=3.0,
                                   lev_cap_eff=1.0 if sizing == "governed" else 5.0,
                                   contract=CONTRACT)
                m = compute_metrics(res.trades)
                runs[f"{sl_name}/{scenario}"] = {"metrics": m, "engine_stats": res.stats}
                logger.info(f"{seg}/{sl_name}/{scenario}: n={m.get('n_trades', 0)} "
                            f"grossR={m.get('gross_expectancy_r', float('nan')):+.4f} "
                            f"netR={m.get('expectancy_r', float('nan')):+.4f} "
                            f"costR={m.get('cost_r', float('nan')):.4f} "
                            f"PF={m.get('profit_factor_net', float('nan')):.3f} "
                            f"skips={res.stats.get('n_skip_size')}")
        report["segments"][seg] = runs

    out = DATA_DIR / "reports" / "w9c_impl_diagnostic.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
