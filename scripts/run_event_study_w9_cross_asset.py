"""W9a/W9b — Cross-asset replication trên BTCUSDT + ETHUSDT (user chủ động yêu cầu).

W9a LEGACY: mọi atom drift-PASS từng có trong ledger + các class kill rẻ tiền có lý do
asset-specific, replicate ĐÚNG ĐỊNH NGHĨA trên BTC/ETH:
- H2b seesaw (chỉ BTC — self-trigger; ETH đã pass trong ledger, skip)
- H4a2 sell-surge reversal long (ETH đã kill trong ledger, skip)
- H9 RSI<30 long, H10b breakdown-fade long, H12 VWAP-stretch long
- H5b premium-low long (cần premium 5m — skip nếu chưa tải xong)
- H3a hour-open long/short, H3b quarter-open long/short
- H7 TSMOM D1 long/short (criteria GỐC riêng: excess@20d ≥ 2%, n ≥ 25, VAL giữ hướng)
- S1 box-at-barrier long/short, S2 H2/L2 pullback long/short, S3 squeeze-release long/short

W9b: 12 atom W8 (chỉ báo textbook — EMA-stack pullback, VWAP reclaim, MACD, Donchian,
RSI50, ADX) trên BTC/ETH — định nghĩa GIỐNG W8 SOL.

Nền tảng: BTC/ETH 5m_enriched (build_dataset_w9.py); 1h resample từ 5m.
Segments: legacy "TRAIN_2020-10_2023-06_{sym}"; W8 "WAVE4_trend_2020-10_2024-06_{sym}".
Judging M2.5: TRAIN excess ≥ 0.05% @+1h (5m) / @+4h (1h), t ≥ 2, CI95lo > 0; VAL cùng dấu
(n_val ≥ 100). HOLDOUT: chỉ TRAIN/VAL — không còn OOS sạch.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w9_cross_asset.py
Output: data/reports/w9_cross_asset.json
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
from solfut.features.indicators import adx, ema, macd, rsi, true_range
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
SEG_LEGACY = "TRAIN_2020-10_2023-06_{sym}"
SEG_W8 = "WAVE4_trend_2020-10_2024-06_{sym}"
CRIT_5M = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
CRIT_1H = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+4h"}
CRIT_H7 = {"n_min": 25, "excess_20d_min_pct": 0.02, "ci95_excess_gt": 0.0, "val_keep_direction": True}
H5 = {"+15m": 3, "+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}
H1F = {"+1h": 1, "+4h": 4, "+24h": 24}


def session_vwap(df: pd.DataFrame) -> pd.Series:
    day = df.index.floor("D")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv / vv


def judge_and_record(hid: str, name: str, source: str, seg: str, crit: dict,
                     df: pd.DataFrame, mask: pd.Series, sign: int,
                     horizons: dict, report: dict) -> None:
    """Pre-register → đo → verdict (M2.5: TRAIN gate + VAL giữ hướng)."""
    hl.register(hid=hid, name=name, source=source, criteria=dict(crit), segment=seg)
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
        "n_events_train": int(res.n_events),
        "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
        "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
        "ci95": [lo, ci.get("hi")], "mfe_mae": res.mfe_mae_stats,
        "val_excess": val_ex, "val_n": int(len(ev_val)),
    }
    hl.record_verdict(hid, verdict, result)
    report[hid] = {"verdict": verdict, "result": result}
    logger.info(f"{hid}: n={res.n_events} ex@{hz}={ex * 100 if ex == ex else float('nan'):+.3f}% "
                f"t={t if t == t else float('nan'):.2f} CIlo={lo} val={val_ex * 100 if val_ex == val_ex else float('nan'):+.3f}% → {verdict}")


def judge_h7(hid: str, name: str, seg: str, df_d1: pd.DataFrame, flip: pd.Series,
             sign: int, report: dict) -> None:
    """H7 criteria GỐC: excess@+20d ≥ 2% (vs baseline vô điều kiện), n ≥ 25, VAL giữ hướng @20d."""
    crit = dict(CRIT_H7)
    hl.register(hid=hid, name=name, source="H7 replicate BTC/ETH (criteria gốc)", criteria=crit, segment=seg)
    fwd20 = df_d1["close"].shift(-20) / df_d1["close"] - 1
    tr_m = (df_d1.index >= T_START) & (df_d1.index <= T_END)
    ev_tr = (sign * fwd20)[flip & tr_m].dropna()
    base_tr = float((sign * fwd20)[tr_m].dropna().mean())
    ex = float(ev_tr.mean() - base_tr) if len(ev_tr) else float("nan")
    se = ev_tr.std(ddof=1) / np.sqrt(len(ev_tr)) if len(ev_tr) > 2 else float("nan")
    t = float((ev_tr.mean() - base_tr) / se) if se and se == se and se > 0 else float("nan")
    ci_ok = bool(len(ev_tr) >= 100)  # bootstrap chỉ có nghĩa n ≥ 100 — ghi n để minh bạch
    val_m = (df_d1.index > T_END) & (df_d1.index <= V_END)
    ev_val = (sign * fwd20)[flip & val_m].dropna()
    base_val = float((sign * fwd20)[val_m].dropna().mean())
    val_ex = float(ev_val.mean() - base_val) if len(ev_val) else float("nan")
    train_ok = bool(len(ev_tr) >= crit["n_min"] and ex == ex and ex >= crit["excess_20d_min_pct"]
                    and ci_ok)   # CI n<100 không xác định → không thể chứng minh → kill trung thực
    val_ok = bool(val_ex == val_ex and val_ex > 0)
    verdict = "pass" if (train_ok and val_ok) else "kill"
    result = {"n_events_train": int(len(ev_tr)), "excess_20d": ex, "t_20d": t,
              "ci_computable": ci_ok, "val_excess_20d": val_ex, "val_n": int(len(ev_val))}
    hl.record_verdict(hid, verdict, result)
    report[hid] = {"verdict": verdict, "result": result}
    logger.info(f"{hid}: n={len(ev_tr)} ex@20d={ex * 100 if ex == ex else float('nan'):+.2f}% "
                f"t={t if t == t else float('nan'):.2f} val={val_ex * 100 if val_ex == val_ex else float('nan'):+.2f}% → {verdict}")


def build_masks_5m(sym: str, m5: pd.DataFrame) -> dict[str, tuple[pd.Series, int, dict]]:
    """{hid: (mask, sign, horizons)} — legacy 5m atoms, defs GIỐNG bản SOL."""
    c, h, l, vol = m5["close"], m5["high"], m5["low"], m5["volume"]
    ret = c.pct_change()
    sigma = ret.rolling(96).std()
    imb = m5["taker_imbalance_fast"]
    imb_z = (imb - imb.rolling(288).mean()) / imb.rolling(288).std()
    rsi14 = m5["rsi14"]
    low48 = l.rolling(48).min().shift(1)
    vol_sma48 = vol.rolling(48).mean().shift(1)
    vwap = session_vwap(m5)
    dev = (c - vwap) / c
    z12 = dev / dev.rolling(8640, min_periods=2880).std()
    minute = m5.index.minute
    out = {
        "H4a2_sell_surge_reversal_long": (imb_z.le(-2).fillna(False), +1, H5),
        "H9_rsi_oversold_long": (rsi14.lt(30).fillna(False), +1, H5),
        "H10b_breakdown_fade_long": ((c < low48) & (vol > 1.5 * vol_sma48), +1, H5),
        "H12_vwap_stretch_fade_long": (z12.le(-2).fillna(False), +1, H5),
        "H3a_hour_open_long": (pd.Series(minute == 0, index=m5.index), +1, H5),
        "H3a_hour_open_short": (pd.Series(minute == 0, index=m5.index), -1, H5),
        "H3b_quarter_open_long": (pd.Series(minute.isin([0, 15, 30, 45]), index=m5.index), +1, H5),
        "H3b_quarter_open_short": (pd.Series(minute.isin([0, 15, 30, 45]), index=m5.index), -1, H5),
    }
    if sym == "BTCUSDT":
        out["H2b_seesaw_long"] = (ret.le(-2 * sigma).fillna(False), +1, H5)
    # S1/S2/S3 — defs GIỐNG book_atoms (enriched có đủ cột)
    price = c
    near_below = (m5["round_above"] - price) <= 0.0015 * price
    near_above = (price - m5["round_below"]) <= 0.0015 * price
    touched_lo = (l <= m5["ema20"]).rolling(3).max().astype(bool)
    touched_hi = (h >= m5["ema20"]).rolling(3).max().astype(bool)
    squeeze_on = ((m5["bb_up"] < m5["kc_up"]) & (m5["bb_low"] > m5["kc_low"])).fillna(False)
    squeeze_ready = squeeze_on.rolling(12).sum() >= 12
    out["S1_box_at_barrier_long"] = ((m5["inside_bar"] & near_below).fillna(False), +1, H5)
    out["S1_box_at_barrier_short"] = ((m5["inside_bar"] & near_above).fillna(False), -1, H5)
    out["S2_h2l2_pullback_long"] = ((m5["reversal_bull"] & touched_lo & m5["always_in_long"]).fillna(False), +1, H5)
    out["S2_l2_pullback_short"] = ((m5["reversal_bear"] & touched_hi & m5["always_in_short"]).fillna(False), -1, H5)
    out["S3_squeeze_release_long"] = ((squeeze_ready & m5["powerbar_bull"]).fillna(False), +1, H5)
    out["S3_squeeze_release_short"] = ((squeeze_ready & m5["powerbar_bear"]).fillna(False), -1, H5)
    return out


def build_masks_w8(m5: pd.DataFrame, h1: pd.DataFrame) -> dict[str, tuple[str, pd.Series, int, dict]]:
    """12 atom W8 — defs GIỐNG run_event_study_w8_indicator_atoms.py (frame-tagged)."""
    c, h, l = m5["close"], m5["high"], m5["low"]
    ema50_5m = ema(c, 50)
    ema2400 = ema(c, 2400)
    vwap = session_vwap(m5)
    vol_mean = m5["volume"].rolling(288, min_periods=48).mean()
    rsi14 = m5["rsi14"]
    up_stack = (c > ema2400) & (m5["ema20"] > ema50_5m) & (c > vwap)
    dn_stack = (c < ema2400) & (m5["ema20"] < ema50_5m) & (c < vwap)
    vol_ok5 = m5["volume"] > 1.5 * vol_mean
    m5a = {
        "W8a_ema_stack_pullback_long": (up_stack & (l <= m5["ema20"]) & (c > m5["ema20"]) & rsi14.between(40, 65), +1, H5),
        "W8a_ema_stack_pullback_short": (dn_stack & (h >= m5["ema20"]) & (c < m5["ema20"]) & rsi14.between(35, 60), -1, H5),
        "W8b_vwap_vol_reclaim_long": (up_stack & (c.shift(1) <= vwap.shift(1)) & vol_ok5, +1, H5),
        "W8b_vwap_vol_reclaim_short": (dn_stack & (c.shift(1) >= vwap.shift(1)) & vol_ok5, -1, H5),
    }

    c1, vol1 = h1["close"], h1["volume"]
    e200 = ema(c1, 200)
    mm = macd(c1)
    hist_up = (mm["hist"] > 0) & (mm["hist"].shift(1) <= 0)
    hist_dn = (mm["hist"] < 0) & (mm["hist"].shift(1) >= 0)
    hh = h1["high"].rolling(240, min_periods=240).max().shift(1)
    ll = h1["low"].rolling(240, min_periods=240).min().shift(1)
    vol_ok1 = vol1 > 1.5 * vol1.rolling(20, min_periods=20).mean()
    r1 = rsi(c1, 14)
    rsi_up = (r1 > 50) & (r1.shift(1) <= 50)
    rsi_dn = (r1 < 50) & (r1.shift(1) >= 50)
    up = h1["high"].diff()
    down = -h1["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=h1.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=h1.index)
    atr_ = true_range(h1).ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_
    mdi = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_
    adx14 = adx(h1, 14)
    nh = c1 >= c1.rolling(20, min_periods=20).max().shift(1)
    nl = c1 <= c1.rolling(20, min_periods=20).min().shift(1)
    h1a = {
        "W8c_macd_trend_cross_long": (hist_up & (c1 > e200), +1, H1F),
        "W8c_macd_trend_cross_short": (hist_dn & (c1 < e200), -1, H1F),
        "W8d_donchian_vol_break_long": ((c1 > hh) & vol_ok1, +1, H1F),
        "W8d_donchian_vol_break_short": ((c1 < ll) & vol_ok1, -1, H1F),
        "W8e_rsi50_trend_long": (rsi_up & (c1 > e200), +1, H1F),
        "W8e_rsi50_trend_short": (rsi_dn & (c1 < e200), -1, H1F),
        "W8f_adx_trend_break_long": ((adx14 > 25) & (pdi > mdi) & (c1 > e200) & nh, +1, H1F),
        "W8f_adx_trend_break_short": ((adx14 > 25) & (mdi > pdi) & (c1 < e200) & nl, -1, H1F),
    }
    out = {}
    for k, v in m5a.items():
        out[k] = ("5m", *v)
    for k, v in h1a.items():
        out[k] = ("1h", *v)
    return out


LEGACY_NAMES = {
    "H2b_seesaw_long": "H2b seesaw long {sym}: BTC(=self) 5m rơi ≥2σ(96) → drift lên",
    "H4a2_sell_surge_reversal_long": "H4a2 sell-surge reversal long {sym}: taker imbalance fast z(288) ≤ −2 → bounce",
    "H9_rsi_oversold_long": "H9 RSI(14) 5m < 30 long {sym} → bounce quá bán",
    "H10b_breakdown_fade_long": "H10b fade-the-breakdown long {sym}: thủng đáy 48-bar + volume 1.5× → drift lên",
    "H12_vwap_stretch_fade_long": "H12 VWAP-stretch long {sym}: z(close−vwap, 30d) ≤ −2 → drift lên về VWAP",
    "H5b_premium_extreme_low_long": "H5b premium rank 30d < p5 long {sym} → drift lên",
    "H3a_hour_open_long": "H3a hour-open long {sym}: nến đầu giờ UTC → drift lên",
    "H3a_hour_open_short": "H3a hour-open short {sym}: nến đầu giờ → drift xuống",
    "H3b_quarter_open_long": "H3b quarter-open long {sym}",
    "H3b_quarter_open_short": "H3b quarter-open short {sym}",
    "S1_box_at_barrier_long": "S1 box-at-barrier long {sym}: inside bar đóng ≤0.15% dưới round number",
    "S1_box_at_barrier_short": "S1 box-at-barrier short {sym}",
    "S2_h2l2_pullback_long": "S2 H2 pullback long {sym}: reversal_bull + chạm EMA20(3 bar) + always-in long",
    "S2_l2_pullback_short": "S2 L2 pullback short {sym}",
    "S3_squeeze_release_long": "S3 squeeze-release long {sym}: BB trong KC ≥12 bar rồi powerbar bull",
    "S3_squeeze_release_short": "S3 squeeze-release short {sym}",
}
W8_NAMES = {
    "W8a_ema_stack_pullback_long": "W8a EMA-stack pullback LONG 5m {sym}",
    "W8a_ema_stack_pullback_short": "W8a EMA-stack pullback SHORT 5m {sym}",
    "W8b_vwap_vol_reclaim_long": "W8b VWAP+volume reclaim LONG 5m {sym}",
    "W8b_vwap_vol_reclaim_short": "W8b VWAP+volume reclaim SHORT 5m {sym}",
    "W8c_macd_trend_cross_long": "W8c MACD trend-cross LONG 1h {sym}",
    "W8c_macd_trend_cross_short": "W8c MACD trend-cross SHORT 1h {sym}",
    "W8d_donchian_vol_break_long": "W8d Donchian-240bar+volume breakout LONG 1h {sym}",
    "W8d_donchian_vol_break_short": "W8d Donchian-240bar+volume breakout SHORT 1h {sym}",
    "W8e_rsi50_trend_long": "W8e RSI50 momentum LONG 1h {sym}",
    "W8e_rsi50_trend_short": "W8e RSI50 momentum SHORT 1h {sym}",
    "W8f_adx_trend_break_long": "W8f ADX-gate breakout LONG 1h {sym}",
    "W8f_adx_trend_break_short": "W8f ADX-gate breakout SHORT 1h {sym}",
}
LEGACY_SKIP_ETH = {"H2b_seesaw_long", "H4a2_sell_surge_reversal_long"}


def main() -> None:
    report: dict = {"segment_note": "W9 cross-asset BTC/ETH — legacy + W8; TRAIN/VAL only, không còn OOS sạch"}
    existing = {r["hid"] for r in hl.load_all()}

    for sym in ("BTCUSDT", "ETHUSDT"):
        m5 = pd.read_parquet(DATA_DIR / f"{sym}_5m_enriched.parquet").sort_index()
        m5 = m5[m5.index <= V_END + pd.Timedelta(days=2)]
        h1 = resample(m5, "1h")

        # ---------- W9a legacy ----------
        masks5 = build_masks_5m(sym, m5)
        for base, (mask, sign, hz) in masks5.items():
            hid = f"{base}_{sym}"
            if hid in existing or (sym == "ETHUSDT" and base in LEGACY_SKIP_ETH):
                report[hid] = {"skipped": "đã có trong ledger"}
                continue
            if base.startswith("H3"):
                src = "H3 seasonality replicate BTC/ETH (M2.6 H3)"
            elif base.startswith(("S1", "S2", "S3")):
                src = "S1/S2/S3 book atoms replicate BTC/ETH (JOTA book strategies)"
            else:
                src = "legacy drift-pass replicate BTC/ETH (định nghĩa GIỐNG bản SOL)"
            judge_and_record(hid, LEGACY_NAMES[base].format(sym=sym), src,
                             SEG_LEGACY.format(sym=sym), dict(CRIT_5M),
                             m5, mask, sign, hz, report)

        # H7 TSMOM D1
        d1 = resample(m5, "1D")
        e20 = ema(d1["close"], 20)
        slope10 = e20 - e20.shift(10)
        up = (d1["close"] > e20) & (slope10 > 0)
        dn = (d1["close"] < e20) & (slope10 < 0)
        for col, flip, sign in (("long", up & ~up.shift(1, fill_value=False), +1),
                                ("short", dn & ~dn.shift(1, fill_value=False), -1)):
            hid = f"H7_tsmom_d1_{col}_{sym}"
            if hid in existing:
                report[hid] = {"skipped": "đã có trong ledger"}
                continue
            judge_h7(hid, f"H7 TSMOM D1 {col} {sym}: state flip EMA20/slope10",
                     SEG_LEGACY.format(sym=sym), d1, flip, sign, report)

        # H5b premium (nếu đã tải)
        hid = f"H5b_premium_extreme_low_long_{sym}"
        prem_path = DATA_DIR / "premium" / f"{sym}_premium_5m.parquet"
        if hid not in existing:
            if prem_path.exists():
                prem = pd.read_parquet(prem_path)["premium"]
                p = prem.reindex(m5.index)
                p_rank = p.rolling(8640, min_periods=2880).rank(pct=True)
                judge_and_record(hid, LEGACY_NAMES["H5b_premium_extreme_low_long"].format(sym=sym),
                                 "H5b replicate BTC/ETH (premium basis REST)",
                                 SEG_LEGACY.format(sym=sym), dict(CRIT_5M),
                                 m5, p_rank.lt(0.05).fillna(False), +1, H5, report)
            else:
                report[hid] = {"skipped": "premium parquet chưa tải xong — đo vòng sau"}

        # ---------- W9b W8 ----------
        masks_w8 = build_masks_w8(m5, h1)
        for base, (frame, mask, sign, hz) in masks_w8.items():
            hid = f"{base}_{sym}"
            if hid in existing:
                report[hid] = {"skipped": "đã có trong ledger"}
                continue
            df = m5 if frame == "5m" else h1
            crit = dict(CRIT_5M if frame == "5m" else CRIT_1H)
            judge_and_record(hid, W8_NAMES[base].format(sym=sym),
                             "W8 indicator atoms replicate BTC/ETH (defs GIỐNG W8 SOL)",
                             SEG_W8.format(sym=sym), crit, df,
                             mask.reindex(df.index).fillna(False), sign, hz, report)

    out = DATA_DIR / "reports" / "w9_cross_asset.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    n_pass = sum(1 for v in report.values() if isinstance(v, dict) and v.get("verdict") == "pass")
    n_kill = sum(1 for v in report.values() if isinstance(v, dict) and v.get("verdict") == "kill")
    logger.info(f"→ {out} | pass={n_pass} kill={n_kill}")


if __name__ == "__main__":
    main()
