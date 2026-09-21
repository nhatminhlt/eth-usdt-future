"""W8 — Event-study 12 atom TREND/MOMENTUM/BREAKOUT từ bộ chỉ báo user đề xuất (lần đầu đo).

Khác lớp fade/mean-rev đã NO-GO ở OOS2: các atom này là trend-continuation —
user chủ động yêu cầu thử (luật: hướng mở chỉ khi user chủ động).

Nguồn: bảng chỉ báo user (EMA 20/50/200, VWAP, ADX, RSI, MACD, BB/KC squeeze,
Donchian-style S/R breakout, volume confirm). Ánh xạ thành 6 cặp atom:

5m (enriched parquet; horizon chấm mặc định +1h):
- W8a_ema_stack_pullback_{long,short}: trend = close > EMA2400(≈EMA200@1h) +
  EMA20 > EMA50 (5m) + đúng bên VWAP phiên; trigger = nến chạm EMA20 và đóng
  giữ được phía trend (long: low ≤ EMA20 & close > EMA20), RSI14 xác nhận 40-65.
- W8b_vwap_vol_reclaim_{long,short}: trend-stack như trên; trigger = close cắt
  LÊN VWAP phiên (từ dưới lên) + volume > 1.5× mean 288 bar.

1h (monthlies; horizon chấm pre-registered +4h — swing anchor của user):
- W8c_macd_trend_cross_{long,short}: MACD(12,26,9) hist cắt 0 theo hướng trend
  + đúng bên EMA200(1h).
- W8d_donchian_vol_break_{long,short}: close vượt high/low 240 bar (10 ngày)
  + volume > 1.5× SMA20(volume).
- W8e_rsi50_trend_{long,short}: đúng bên EMA200(1h) + RSI14 cắt lên/xuống 50.
- W8f_adx_trend_break_{long,short}: ADX14 > 25, DI đúng hướng, đúng bên
  EMA200(1h), close lập đỉnh/đáy mới 20 bar.

Tiêu chí M2.5 mặc định (pre-registered): TRAIN excess ≥ 0.05% @horizon đăng ký,
t ≥ 2, CI95 lo > 0; VAL cùng dấu (n_val ≥ 100). HOLDOUT LƯU Ý: OOS1/OOS2 đã
tiêu cho lớp fade — atom W8 chỉ chấm trên TRAIN/VAL; mọi kết quả đều dán nhãn
exploratory, không có holdout sạch còn lại cho lớp này.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w8_indicator_atoms.py
Output: data/reports/w8_indicator_atoms.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.features.indicators import adx, atr, ema, macd, rsi
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
SEG = "WAVE4_trend_2020-10_2024-06"
CRIT_1H = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}    # 5m atoms
CRIT_4H = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+4h"}    # 1h atoms
H5 = {"+15m": 3, "+1h": 12, "+4h": 48}
H1 = {"+1h": 1, "+4h": 4, "+24h": 24}


def session_vwap(df: pd.DataFrame) -> pd.Series:
    day = df.index.floor("D")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv / vv


def plus_minus_di(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    from solfut.features.indicators import true_range
    atr_ = true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    return 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_, \
        100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_


def build_masks_5m(sol: pd.DataFrame) -> dict[str, pd.Series]:
    c, h, l = sol["close"], sol["high"], sol["low"]
    ema50 = ema(c, 50)
    ema2400 = ema(c, 2400)                     # ≈ EMA200 trên 1h
    vwap = session_vwap(sol)
    vol_mean = sol["volume"].rolling(288, min_periods=48).mean()
    rsi14 = sol["rsi14"]

    up_stack = (c > ema2400) & (sol["ema20"] > ema50) & (c > vwap)
    dn_stack = (c < ema2400) & (sol["ema20"] < ema50) & (c < vwap)

    pb_long = up_stack & (l <= sol["ema20"]) & (c > sol["ema20"]) & rsi14.between(40, 65)
    pb_short = dn_stack & (h >= sol["ema20"]) & (c < sol["ema20"]) & rsi14.between(35, 60)

    vol_ok = sol["volume"] > 1.5 * vol_mean
    rc_long = (c > ema2400) & (sol["ema20"] > ema50) & (c > vwap) & (c.shift(1) <= vwap.shift(1)) & vol_ok
    rc_short = (c < ema2400) & (sol["ema20"] < ema50) & (c < vwap) & (c.shift(1) >= vwap.shift(1)) & vol_ok
    return {
        "W8a_ema_stack_pullback_long": pb_long.fillna(False),
        "W8a_ema_stack_pullback_short": pb_short.fillna(False),
        "W8b_vwap_vol_reclaim_long": rc_long.fillna(False),
        "W8b_vwap_vol_reclaim_short": rc_short.fillna(False),
    }


def build_masks_1h(h1: pd.DataFrame) -> dict[str, pd.Series]:
    c, vol = h1["close"], h1["volume"]
    e200 = ema(c, 200)
    m = macd(c)
    hist_up = (m["hist"] > 0) & (m["hist"].shift(1) <= 0)
    hist_dn = (m["hist"] < 0) & (m["hist"].shift(1) >= 0)

    hh = h1["high"].rolling(240, min_periods=240).max().shift(1)
    ll = h1["low"].rolling(240, min_periods=240).min().shift(1)
    vol_ok = vol > 1.5 * vol.rolling(20, min_periods=20).mean()

    r = rsi(c, 14)
    rsi_up = (r > 50) & (r.shift(1) <= 50)
    rsi_dn = (r < 50) & (r.shift(1) >= 50)

    pdi, mdi = plus_minus_di(h1, 14)
    adx14 = adx(h1, 14)
    nh = c >= c.rolling(20, min_periods=20).max().shift(1)
    nl = c <= c.rolling(20, min_periods=20).min().shift(1)

    return {
        "W8c_macd_trend_cross_long": (hist_up & (c > e200)).fillna(False),
        "W8c_macd_trend_cross_short": (hist_dn & (c < e200)).fillna(False),
        "W8d_donchian_vol_break_long": ((c > hh) & vol_ok).fillna(False),
        "W8d_donchian_vol_break_short": ((c < ll) & vol_ok).fillna(False),
        "W8e_rsi50_trend_long": (rsi_up & (c > e200)).fillna(False),
        "W8e_rsi50_trend_short": (rsi_dn & (c < e200)).fillna(False),
        "W8f_adx_trend_break_long": ((adx14 > 25) & (pdi > mdi) & (c > e200) & nh).fillna(False),
        "W8f_adx_trend_break_short": ((adx14 > 25) & (mdi > pdi) & (c < e200) & nl).fillna(False),
    }


ATOMS = [
    # (hid, name, frame, sign, criteria, horizons)
    ("W8a_ema_stack_pullback_long",
     "EMA-stack pullback LONG 5m: close>EMA2400 + EMA20>EMA50 + close>VWAP; nến chạm EMA20 đóng giữ, RSI 40-65",
     "5m", +1, CRIT_1H, H5),
    ("W8a_ema_stack_pullback_short",
     "EMA-stack pullback SHORT 5m: mirror — close<EMA2400 + EMA20<EMA50 + close<VWAP; chạm EMA20 đóng giữ, RSI 35-60",
     "5m", -1, CRIT_1H, H5),
    ("W8b_vwap_vol_reclaim_long",
     "VWAP+volume reclaim LONG 5m: trend-stack + close cắt LÊN VWAP phiên + volume >1.5×mean288",
     "5m", +1, CRIT_1H, H5),
    ("W8b_vwap_vol_reclaim_short",
     "VWAP+volume reclaim SHORT 5m: mirror — cắt XUỐNG VWAP + volume confirm",
     "5m", -1, CRIT_1H, H5),
    ("W8c_macd_trend_cross_long",
     "MACD trend-cross LONG 1h: hist(12,26,9) cắt 0 lên + close>EMA200(1h)",
     "1h", +1, CRIT_4H, H1),
    ("W8c_macd_trend_cross_short",
     "MACD trend-cross SHORT 1h: hist cắt 0 xuống + close<EMA200(1h)",
     "1h", -1, CRIT_4H, H1),
    ("W8d_donchian_vol_break_long",
     "Donchian+volume breakout LONG 1h: close vượt high 240 bar (10 ngày) + volume>1.5×SMA20",
     "1h", +1, CRIT_4H, H1),
    ("W8d_donchian_vol_break_short",
     "Donchian+volume breakout SHORT 1h: close thủng low 240 bar + volume confirm",
     "1h", -1, CRIT_4H, H1),
    ("W8e_rsi50_trend_long",
     "RSI50 momentum LONG 1h: close>EMA200 + RSI14 cắt lên 50",
     "1h", +1, CRIT_4H, H1),
    ("W8e_rsi50_trend_short",
     "RSI50 momentum SHORT 1h: close<EMA200 + RSI14 cắt xuống 50",
     "1h", -1, CRIT_4H, H1),
    ("W8f_adx_trend_break_long",
     "ADX-gate breakout LONG 1h: ADX14>25 + DI+>DI− + close>EMA200 + đỉnh mới 20 bar",
     "1h", +1, CRIT_4H, H1),
    ("W8f_adx_trend_break_short",
     "ADX-gate breakout SHORT 1h: ADX14>25 + DI−>DI+ + close<EMA200 + đáy mới 20 bar",
     "1h", -1, CRIT_4H, H1),
]


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]
    h1 = load_monthlies("SOLUSDT", "1h")
    for col in ("open", "high", "low", "close", "volume"):
        h1[col] = pd.to_numeric(h1[col], errors="coerce")
    h1.index = pd.to_datetime(h1["open_time"], unit="ms", utc=True)
    h1 = h1.sort_index()
    h1 = h1[h1.index <= V_END + pd.Timedelta(days=2)]

    masks5 = build_masks_5m(sol)
    masks1 = build_masks_1h(h1)

    for hid, name, frame, sign, crit, _ in ATOMS:
        hl.register(hid=hid, name=name,
                    source="W8 — user chủ động yêu cầu thử bộ chỉ báo phổ biến "
                           "(EMA stack/VWAP/MACD/RSI/ADX/Donchian+volume)",
                    criteria=dict(crit), segment=SEG)

    report: dict = {"segment": SEG, "note": "trend/momentum/breakout class — KHÔNG có holdout sạch (OOS1/OOS2 đã tiêu cho lớp fade)"}
    for hid, name, frame, sign, crit, horizons in ATOMS:
        df, mask = (sol, masks5[hid]) if frame == "5m" else (h1, masks1[hid])
        res = events.run_event_study(df, mask, hid, horizons=horizons, sign=sign)
        hz = crit["horizon"]
        ex = res.excess_by_horizon.get(hz)
        t = res.t_by_horizon.get(hz)
        ci = res.ci_event_by_horizon.get(hz, {})
        lo = ci.get("lo")
        train_ok = bool(ex == ex and ex >= crit["excess_min_pct"] and t == t
                        and t >= crit["t_min"] and lo == lo and lo is not None and lo > 0)
        hbars = horizons[hz]
        fwd = df["close"].shift(-hbars) / df["close"] - 1
        val_m = mask & (df.index > T_END) & (df.index <= V_END)
        ev_val = (sign * fwd).loc[df.index[val_m]].dropna()
        seg_val = (df.index > T_END) & (df.index <= V_END)
        base_val = float((sign * fwd)[seg_val].dropna().mean())
        val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 100 else float("nan")
        val_ok = bool(val_ex == val_ex and val_ex > 0)
        verdict = "pass" if (train_ok and val_ok) else "kill"
        result = {
            "frame": frame, "n_events_train": int(res.n_events),
            "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
            "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
            "ci95": [lo, ci.get("hi")], "mfe_mae": res.mfe_mae_stats,
            "train_gate": train_ok, "val_excess": val_ex, "val_n": int(len(ev_val)),
        }
        hl.record_verdict(hid, verdict, result)
        report[hid] = {"verdict": verdict, "result": result}
        logger.info(f"{hid}: n={res.n_events} ex@{hz}={ex * 100 if ex == ex else float('nan'):+.3f}% "
                    f"t={t if t == t else float('nan'):.2f} CIlo={lo} val={val_ex * 100 if val_ex == val_ex else float('nan'):+.3f}% "
                    f"(n={len(ev_val)}) → {verdict}")
        logger.info("    decay: " + " ".join(f"{k}={v * 100:+.3f}%" for k, v in res.excess_by_horizon.items()))

    out = DATA_DIR / "reports" / "w8_indicator_atoms.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
