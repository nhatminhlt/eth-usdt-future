"""W5 bước 1 — Stress attribution của cấu hình FROZEN ensemble-8 (measure-only, không tốn
ledger, không đụng OOS). Câu hỏi: expectancy của chính chuỗi lệnh đó chia theo BẬC vol
TUYỆT ĐỐI tại bar signal — cơ chế a-priori: liquidity refill sau forced selling chỉ có
thịnh hành trong stress; nếu edge không tập trung ở bậc cao → regime gate vô ích.

Bậc (ladder mechanism-anchored từ anchor ATR5m = 0.20% của settings): <0.2 noise /
0.2–0.4 normal / 0.4–0.8 elevated / ≥0.8 stress-shock / ≥1.6 panic.

=== QUY TẮC ĐỌC pre-registered (TRƯỚC KHI CHẠY) ===
- Ứng viên gate = bậc ≥0.8% nếu thoả CẢ: (a) pooled n ≥ 100, (b) TRAIN expectancy_r CI95
  (block bootstrap) > 0 và expectancy ≥ 0.05R, (c) VAL cùng bậc expectancy > 0, (d) OOS1
  cùng bậc expectancy > 0. Kiểm cả ≥1.6% nếu n đủ (≥ 150 TRAIN).
- Dự phòng: nếu n(≥0.8%) < 100 nhưng bậc ≥0.4% thoả điều kiện và expectancy bậc cao
  không giảm so với ≥0.8% → gate >0.4%.
- Nếu KHÔNG bậc nào thoả → HOLD OFF: edge không thuần stress ở mức absolute → khuyến nghị
  chuyển sang venue/fee hoặc NO-GO, không tiêu OOS2.
- Frequency check: lệnh/năm của gate-pool (8 symbol) ≥ 200 → đủ đi tiếp (plan đề nghị 300;
  dưới 300 cần user phê chuẩn ngoại lệ low-frequency).

Chạy: .venv/Scripts/python.exe scripts/run_w5_stress_attribution.py
Output: data/reports/w5_stress_attribution.json
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

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
HOLDING = 48
SEGMENTS = {
    "TRAIN": (pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")),
    "VAL": (pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-06-30 23:59", tz="UTC")),
    "OOS1": (pd.Timestamp("2024-07-01", tz="UTC"), pd.Timestamp("2025-08-31 23:59", tz="UTC")),
}
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0
LADDER = [0.0, 0.2, 0.4, 0.8, 1.6]     # % ATR — nhãn bucket từ licycle


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

    rows = []
    sl_by_sym: dict = {}
    for seg, (s0, s1) in SEGMENTS.items():
        all_tr = []
        for sym in SYMBOLS:
            try:
                df = load_5m(sym)
            except FileNotFoundError:
                logger.warning(f"{sym}: thiếu dữ liệu — bỏ qua")
                continue
            atr_abs = abs_atr_pct(df)
            df_seg = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
            atr_rank = df["atr_abs_rank"] if False else None
            # atrRank>0.70 tier — tính từ rolling rank của abs_atr (30 ngày), causal
            stats_rank = atr_abs.rolling(8640, min_periods=2880).rank(pct=True)
            rank_seg = stats_rank.loc[df_seg.index]
            unb0 = btc_jump_mask(df_seg.index) & rank_seg.gt(0.70).fillna(False)
            ev_idx = df_seg.index[unb0 & (df_seg.index <= s1)]

            if seg == "TRAIN" and sym not in sl_by_sym:
                df_tr = df[(df.index >= SEGMENTS["TRAIN"][0])
                           & (df.index <= SEGMENTS["TRAIN"][1] + pd.Timedelta(days=2))]
                rank_tr = stats_rank.loc[df_tr.index]
                mask_tr = btc_jump_mask(df_tr.index) & rank_tr.gt(0.70).fillna(False)
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
            res = run_backtest(df_seg, sig, load_cost_model(), scenario="maker_base",
                               bound="sl_first", activity=None,
                               funding=FundingSchedule.load(sym), equity_start=50.0,
                               sizing="governed", risk_cap_pct=RISK_CAP_PCT,
                               lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym],
                               exit_maker=True, exit_patience=12)
            if len(res.trades):
                tr = res.trades.assign(symbol=sym)
                tr["atr_abs_pct"] = atr_abs.loc[tr["signal_time"]].values
                all_tr.append(tr)
        if all_tr:
            lo_pool = pd.concat(all_tr, ignore_index=True)
            rows.append((seg, lo_pool))
            logger.info(f"[{seg}] trades: {len(lo_pool)}")

    # ===== bucket theo ladder =====
    bucket_labels = ["<0.2", "0.2-0.4", "0.4-0.8", ">=0.8", ">=1.6"]
    def bucket_of(v: float) -> str:
        if v >= 1.6: return ">=1.6"
        if v >= 0.8: return ">=0.8"
        if v >= 0.4: return "0.4-0.8"
        if v >= 0.2: return "0.2-0.4"
        return "<0.2"

    result: dict = {"config": "frozen ensemble-8 maker/maker governed", "buckets": {}}
    for seg, tr in rows:
        per = {}
        span_years = max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)
        for bl in bucket_labels:
            if bl == ">=1.6":
                sub = tr[tr["atr_abs_pct"] >= 1.6]
            elif bl == ">=0.8":
                sub = tr[tr["atr_abs_pct"] >= 0.8]
            elif bl == "0.4-0.8":
                sub = tr[(tr["atr_abs_pct"] >= 0.4) & (tr["atr_abs_pct"] < 0.8)]
            else:
                sub = tr[(tr["atr_abs_pct"] >= 0.2) & (tr["atr_abs_pct"] < 0.4)] \
                    if bl == "0.2-0.4" else tr[tr["atr_abs_pct"] < 0.2]
            if len(sub) == 0:
                per[bl] = {"n": 0}
                continue
            r = sub["r_net"].to_numpy(float)
            lo, hi = bootstrap_expectancy_ci(r) if len(r) >= 100 else (float("nan"), float("nan"))
            per[bl] = {
                "n": int(len(sub)), "expectancy_r": float(np.nanmean(r)),
                "ci95": [lo, hi], "win_rate": float((sub["net_pnl"] > 0).mean()),
                "net_usdt": float(sub["net_pnl"].sum()),
                "trades_per_year": float(len(sub) / span_years),
                "by_symbol": sub.groupby("symbol")["r_net"].mean().round(4).to_dict(),
            }
        result["buckets"][seg] = per
        logger.info(f"[{seg}] " + " | ".join(
            f"{bl}: n={d['n']} ex={d.get('expectancy_r', float('nan')):.4f}"
            for bl, d in per.items() if d["n"]))

    # ===== áp quy tắc đọc pre-registered =====
    trb = result["buckets"]["TRAIN"]
    def gate_check(bl, tr_p):
        tr = trb[bl]
        if tr["n"] < 150:                       # (a) n tối thiểu (d functional: 100/150 theo quy tắc)
            return False, f"n={tr['n']} <150"
        lo = tr["ci95"][0]
        if not (lo == lo and lo > 0):           # (b) CI > 0
            return False, f"CI lo={lo}"
        if tr["expectancy_r"] < 0.05:           # (b) expectancy ≥ 0.05R
            return False, f"ex={tr['expectancy_r']:.4f} <0.05"
        for seg, tr_seg in result["buckets"].items():
            if seg == "TRAIN":
                continue
            d = tr_seg.get(bl, {"n": 0})
            if d["n"] < 50:
                return False, f"{seg} n={d['n']} <50"
            if d.get("expectancy_r", 0) <= 0:   # (c,d) cùng dấu dương
                return False, f"{seg} ex={d.get('expectancy_r'):.4f} <=0"
        # frequency: lệnh/năm pooled gate ≥ 200
        fy = max(tr["trades_per_year"], 0)
        if fy < 200:
            return False, f"freq={fy:.0f}/năm <200"
        return True, "OK"

    for bl in (">=1.6", ">=0.8", "0.4-0.8"):
        ok, why = gate_check(bl, result)
        result.setdefault("gate_check", {})[bl] = {"pass": ok, "reason": why}
        logger.info(f"GATE {bl}: {'PASS' if ok else 'FAIL'} — {why}")

    out = DATA_DIR / "reports" / "w5_stress_attribution.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
