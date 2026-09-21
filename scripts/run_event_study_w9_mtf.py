"""W9c — MULTI-TIMEFRAME STACK (lần đầu đo thật sự — các wave trước đơn khung).

Kiến trúc: D1 = hướng lớn (close > EMA200 D1 = bull / < = bear, warmup 200 phiên —
sự kiện trước 2021-05 tự động rơi), H4 = setup, H1 = trigger (W9c1-W9c3) hoặc
M15 = trigger (W9c4). ĐIỀU KIỆN KHUNG CAO CHỈ DÙNG BAR ĐÃ ĐÓNG:
- D1: giá trị của NGÀY TRƯỚC (t.floor('D') − 1 ngày)
- H4: bar H4 TRƯỚC bar đang chứa t (t.floor('4h') − 4h)

8 atom/asset × 3 asset (SOL/BTC/ETH), segment mới "WAVE5_MTF_2020-10_2024-06_{sym}":
- W9c1_mtf_trend_rsi_{long,short}: D1 bull/bear & EMA20(H4)>EMA50(H4) & RSI14(H1) cắt 50
- W9c2_mtf_pullback_{long,short}: D1 & close vs EMA20(H4) cùng chiều & H1 pullback chạm
  EMA20(H1) đóng giữ
- W9c3_mtf_macd_break_{long,short}: D1 & MACD-hist(H4) cùng dấu & H1 close phá đỉnh/đáy 20 bar
- W9c4_mtf_m15_pullback_{long,short}: D1 & EMA20(H4) stack & close>EMA20(H1) & M15 pullback
  chạm EMA20(M15) đóng giữ (trigger M15 → label từ bar M15)

Criteria: M2.5 mặc định @+4h (excess ≥ 0.05%, t ≥ 2, CI95lo > 0 TRAIN); VAL cùng dấu
(n ≥ 100). Horizons theo frame trigger: H1 → {+4h:4, +24h:24}; M15 → {+4h:16, +24h:96}.
HOLDOUT: chỉ TRAIN/VAL — không còn OOS sạch.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w9_mtf.py
Output: data/reports/w9_mtf.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.data.resample import resample
from solfut.features.indicators import ema, macd, rsi
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
CRIT = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+4h"}
H_H1 = {"+4h": 4, "+24h": 24}
H_M15 = {"+4h": 16, "+24h": 96}

MTF_NAMES = {
    "W9c1_mtf_trend_rsi_long": "MTF trend+RSI LONG {sym}: D1 bull(EMA200) & EMA20(H4)>EMA50(H4) & RSI14(H1) cắt lên 50",
    "W9c1_mtf_trend_rsi_short": "MTF trend+RSI SHORT {sym}: mirror",
    "W9c2_mtf_pullback_long": "MTF pullback LONG {sym}: D1 bull & close>EMA20(H4) & H1 chạm EMA20(H1) đóng giữ",
    "W9c2_mtf_pullback_short": "MTF pullback SHORT {sym}: mirror",
    "W9c3_mtf_macd_break_long": "MTF MACD-break LONG {sym}: D1 bull & MACD-hist(H4)>0 & H1 phá đỉnh 20 bar",
    "W9c3_mtf_macd_break_short": "MTF MACD-break SHORT {sym}: mirror",
    "W9c4_mtf_m15_pullback_long": "MTF M15-timed pullback LONG {sym}: D1 bull & EMA20(H4)>EMA50(H4) & close>EMA20(H1) & M15 chạm EMA20(M15) đóng giữ",
    "W9c4_mtf_m15_pullback_short": "MTF M15-timed pullback SHORT {sym}: mirror",
}


def hprev(s: pd.Series, trigger_idx: pd.DatetimeIndex, freq: str, offset: pd.Timedelta) -> pd.Series:
    """Giá trị bar KHUNG CAO đã đóng trước thời điểm t (map về index trigger)."""
    key = trigger_idx.floor(freq) - offset
    return pd.Series(s.reindex(key).values, index=trigger_idx)


def dprev(s: pd.Series, trigger_idx: pd.DatetimeIndex) -> pd.Series:
    key = trigger_idx.floor("D") - pd.Timedelta(days=1)
    return pd.Series(s.reindex(key).values, index=trigger_idx)


def main() -> None:
    report: dict = {"segment_note": "W9c MTF stack D1→H4→H1/M15 — lần đầu đo; TRAIN/VAL only"}
    existing = {r["hid"] for r in hl.load_all()}

    for sym in ("SOLUSDT", "BTCUSDT", "ETHUSDT"):
        m5 = pd.read_parquet(DATA_DIR / f"{sym}_5m_enriched.parquet").sort_index()
        m5 = m5[m5.index <= V_END + pd.Timedelta(days=2)]
        h1 = resample(m5, "1h")
        h4 = resample(m5, "4h")
        d1 = resample(m5, "1D")
        m15 = resample(m5, "15min")

        # khung cao — tính trên frame riêng
        d1_ema200 = ema(d1["close"], 200)
        d1_bull_day = (d1["close"] > d1_ema200).shift(0)   # map theo ngày trước tại trigger
        d1_bear_day = (d1["close"] < d1_ema200).shift(0)
        h4_e20, h4_e50 = ema(h4["close"], 20), ema(h4["close"], 50)
        h4_hist = macd(h4["close"])["hist"]

        # ----- trigger H1 -----
        idx = h1.index
        bull = dprev(d1_bull_day, idx).fillna(False)
        bear = dprev(d1_bear_day, idx).fillna(False)
        h4_up = (hprev(h4_e20, idx, "4h", pd.Timedelta(hours=4))
                 > hprev(h4_e50, idx, "4h", pd.Timedelta(hours=4))).fillna(False)
        h4_dn = ~h4_up
        h4_hist_prev = hprev(h4_hist, idx, "4h", pd.Timedelta(hours=4))
        c1 = h1["close"]
        e20_1 = ema(c1, 20)
        r1 = rsi(c1, 14)
        rsi_up = (r1 > 50) & (r1.shift(1) <= 50)
        rsi_dn = (r1 < 50) & (r1.shift(1) >= 50)
        hh20 = c1.rolling(20, min_periods=20).max().shift(1)
        ll20 = c1.rolling(20, min_periods=20).min().shift(1)
        pull_lo = (h1["low"] <= e20_1) & (c1 > e20_1)
        pull_hi = (h1["high"] >= e20_1) & (c1 < e20_1)

        h1_atoms = {
            "W9c1_mtf_trend_rsi_long": (bull & h4_up & rsi_up, +1),
            "W9c1_mtf_trend_rsi_short": (bear & h4_dn & rsi_dn, -1),
            "W9c2_mtf_pullback_long": (bull & (c1 > hprev(h4_e20, idx, "4h", pd.Timedelta(hours=4))) & pull_lo, +1),
            "W9c2_mtf_pullback_short": (bear & (c1 < hprev(h4_e20, idx, "4h", pd.Timedelta(hours=4))) & pull_hi, -1),
            "W9c3_mtf_macd_break_long": (bull & (h4_hist_prev > 0) & (c1 >= hh20), +1),
            "W9c3_mtf_macd_break_short": (bear & (h4_hist_prev < 0) & (c1 <= ll20), -1),
        }

        # ----- trigger M15 -----
        idx15 = m15.index
        bull15 = dprev(d1_bull_day, idx15).fillna(False)
        bear15 = dprev(d1_bear_day, idx15).fillna(False)
        h4_up15 = (hprev(h4_e20, idx15, "4h", pd.Timedelta(hours=4))
                   > hprev(h4_e50, idx15, "4h", pd.Timedelta(hours=4))).fillna(False)
        h4_dn15 = ~h4_up15
        c15 = m15["close"]
        e20_15 = ema(c15, 20)
        e20_1_map = hprev(e20_1.reindex(h1.index).ffill(), idx15, "1h", pd.Timedelta(hours=1))
        pull15_lo = (m15["low"] <= e20_15) & (c15 > e20_15)
        pull15_hi = (m15["high"] >= e20_15) & (c15 < e20_15)
        m15_atoms = {
            "W9c4_mtf_m15_pullback_long": (bull15 & h4_up15 & (c15 > e20_1_map) & pull15_lo, +1),
            "W9c4_mtf_m15_pullback_short": (bear15 & h4_dn15 & (c15 < e20_1_map) & pull15_hi, -1),
        }

        seg = f"WAVE5_MTF_2020-10_2024-06_{sym}"
        for base, (mask, sign) in h1_atoms.items():
            hid = f"{base}_{sym}"
            hl.register(hid=hid, name=MTF_NAMES[base].format(sym=sym),
                        source="W9c MTF stack (user yêu cầu trade đồng thời M15/H1/H4/D1)",
                        criteria=dict(CRIT), segment=seg)
            res = events.run_event_study(h1, mask.fillna(False), hid, horizons=H_H1, sign=sign)
            _record(hid, res, h1, mask.fillna(False), sign, H_H1, report)
        for base, (mask, sign) in m15_atoms.items():
            hid = f"{base}_{sym}"
            hl.register(hid=hid, name=MTF_NAMES[base].format(sym=sym),
                        source="W9c MTF stack — trigger M15",
                        criteria=dict(CRIT), segment=seg)
            res = events.run_event_study(m15, mask.fillna(False), hid, horizons=H_M15, sign=sign)
            _record(hid, res, m15, mask.fillna(False), sign, H_M15, report)

    out = DATA_DIR / "reports" / "w9_mtf.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    n_pass = sum(1 for v in report.values() if isinstance(v, dict) and v.get("verdict") == "pass")
    logger.info(f"→ {out} | pass={n_pass}")


def _record(hid: str, res, df: pd.DataFrame, mask: pd.Series, sign: int,
            horizons: dict, report: dict) -> None:
    hz = "+4h"
    ex = res.excess_by_horizon.get(hz)
    t = res.t_by_horizon.get(hz)
    ci = res.ci_event_by_horizon.get(hz, {})
    lo = ci.get("lo")
    train_ok = bool(ex == ex and ex >= 0.0005 and t == t and t >= 2.0
                    and lo == lo and lo is not None and lo > 0)
    fwd = df["close"].shift(-horizons[hz]) / df["close"] - 1
    val_m = mask & (df.index > T_END) & (df.index <= V_END)
    ev_val = (sign * fwd).loc[df.index[val_m]].dropna()
    seg_val = (df.index > T_END) & (df.index <= V_END)
    base_val = float((sign * fwd)[seg_val].dropna().mean())
    val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 100 else float("nan")
    val_ok = bool(val_ex == val_ex and val_ex > 0)
    verdict = "pass" if (train_ok and val_ok) else "kill"
    result = {
        "n_events_train": int(res.n_events),
        "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
        "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
        "ci95": [lo, ci.get("hi")],
        "val_excess": val_ex, "val_n": int(len(ev_val)),
    }
    hl.record_verdict(hid, verdict, result)
    report[hid] = {"verdict": verdict, "result": result}
    logger.info(f"{hid}: n={res.n_events} ex@+4h={ex * 100 if ex == ex else float('nan'):+.3f}% "
                f"t={t if t == t else float('nan'):.2f} CIlo={lo} "
                f"val={val_ex * 100 if val_ex == val_ex else float('nan'):+.3f}% → {verdict}")


if __name__ == "__main__":
    main()
