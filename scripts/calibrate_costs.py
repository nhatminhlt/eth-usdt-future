"""M1 mục 16: calibrate chi phí từ aggTrades THẬT (30 ngày gần nhất, mở rộng được ra 2 tháng).

Đo 3 thứ (PLAN M1/M4):
1. Spread hiệu dụng theo giờ — Roll estimator: 2*sqrt(-cov(Δp, Δp_lag1)) (bps).
2. Impact theo size — bucket notional (decile), đo signed move 5 giây sau lệnh taker (bps).
3. Điều kiện STOP — 5m bar có range ≥ 3×ATR5m (proxy lúc stop cascade):
   spread của những phút đó so với phút thường → hệ số slippage-lúc-stop
   (đối chiếu hệ số 1.5 mà V1 từng dùng).

Output: data/costs/slippage_hourly.parquet, slippage_size_impact.parquet,
        cost_calibration_summary.json

Chạy: .venv/Scripts/python.exe scripts/calibrate_costs.py
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solfut.data.downloader import DATA_DIR, VISION

SYMBOL = "SOLUSDT"
N_DAYS = 30
COST_DIR = DATA_DIR / "costs"
AGG_DIR = DATA_DIR / "aggTrades" / SYMBOL

AGG_COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
            "transact_time", "is_buyer_maker"]


def download_daily_agg(date_iso: str) -> Path | None:
    AGG_DIR.mkdir(parents=True, exist_ok=True)
    out = AGG_DIR / f"{SYMBOL}-aggTrades-{date_iso}.parquet"
    if out.exists():
        return out
    url = f"{VISION}/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{date_iso}.zip"
    r = requests.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    lines = raw.strip().split("\n")
    header = None
    try:
        float(lines[0].split(",")[1])
    except (ValueError, IndexError):
        header = lines[0].split(",")
        lines = lines[1:]
    df = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=header or AGG_COLS)
    df.to_parquet(out, index=False)
    return out


def roll_spread_bps(log_prices: np.ndarray) -> float:
    """Roll (1984) effective spread theo bps: 2*sqrt(-cov(Δp, Δp_lag1)) × 1e4."""
    if len(log_prices) < 100:
        return np.nan
    dp = np.diff(log_prices)
    cov = np.cov(dp[:-1], dp[1:])[0, 1]
    if cov >= 0:  # estimator chỉ hợp lệ khi cov âm (bid-ask bounce)
        return np.nan
    return float(2 * np.sqrt(-cov) * 1e4)


def process_day(path: Path, atr5m: float) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = pd.read_parquet(path)
    df["price"] = df["price"].astype("float64")
    df["quantity"] = df["quantity"].astype("float64")
    df["ts"] = pd.to_datetime(df["transact_time"].astype("int64"), unit="ms")
    df["notional"] = df["price"] * df["quantity"]
    df["minute"] = df["ts"].dt.floor("5min")
    df["hour"] = df["ts"].dt.hour
    df["logp"] = np.log(df["price"])

    # 1) Roll spread theo giờ
    hourly = df.groupby("hour")["logp"].apply(lambda s: roll_spread_bps(s.values))
    vol_h = df.groupby("hour")["notional"].sum()
    n_h = df.groupby("hour").size()

    # 2) Impact theo size bucket: signed move 5s sau mỗi lệnh taker
    df = df.sort_values("transact_time").reset_index(drop=True)
    times = df["transact_time"].astype("int64").values
    prices = df["price"].values
    idx_5s = np.searchsorted(times, times + 5_000)
    fwd_move_bps = (prices[np.minimum(idx_5s, len(prices) - 1)] / prices - 1) * 1e4
    # taker BUY (is_buyer_maker=False) → chiều +1; taker SELL → −1
    direction = np.where(df["is_buyer_maker"].astype(str).str.lower().isin(["false", "0"]), 1.0, -1.0)
    tmp = pd.DataFrame({"notional": df["notional"].values, "signed": fwd_move_bps * direction})
    buckets = pd.qcut(tmp["notional"], 10, duplicates="drop")
    g = tmp.groupby(buckets, observed=True)
    size_impact = pd.DataFrame({
        "bucket_mid_notional": g["notional"].median(),
        "impact_5s_bps_abs": g["signed"].apply(lambda s: s.abs().mean()),
        "n": g.size(),
    }).reset_index(drop=True)

    # 3) Điều kiện stop: 5m bar có range ≥ 3×ATR5m.
    #    Đo burst-factor: median |log-ret 1 giây| trong phút stop vs toàn phiên —
    #    robust hơn Roll spread trên subset nhỏ (Roll thường không xác định được).
    bar = df.groupby("minute").agg(high=("price", "max"), low=("price", "min"))
    bar["range"] = bar["high"] - bar["low"]
    stop_bars = bar["range"] >= 3 * atr5m
    stop_minutes = set(bar.index[stop_bars])
    df["second"] = df["ts"].dt.floor("1s")
    sec = df.groupby("second")["logp"].last()
    ret1s = sec.diff().abs().dropna()
    sec_minute = pd.Series(sec.index.floor("5min"), index=sec.index)
    is_stop_sec = sec_minute.isin(stop_minutes).reindex(ret1s.index)
    base = float(ret1s.median())
    stop_med = float(ret1s[is_stop_sec].median()) if is_stop_sec.any() else np.nan
    day_info = {
        "burst_mult": (stop_med / base) if (base and base > 0 and stop_med == stop_med) else np.nan,
        "stop_bar_ratio": float(stop_bars.mean()),
        "roll_hour_ratios": {},
    }
    hour_map = df.groupby("minute")["hour"].first()
    for h in sorted(df["hour"].unique()):
        sub = df[df["hour"] == h]
        normal = roll_spread_bps(sub["logp"].values)
        stop_s = roll_spread_bps(sub[sub["minute"].isin(stop_minutes)]["logp"].values)
        day_info["roll_hour_ratios"][int(h)] = {"spread_normal_bps": normal, "spread_stop_bps": stop_s}

    hourly_df = pd.DataFrame({
        "hour": hourly.index.astype(int),
        "roll_spread_bps": hourly.values,
        "quote_volume": (vol_h / N_DAYS).values,
        "n_trades": (n_h / N_DAYS).values,
    })
    return hourly_df, size_impact, day_info


def main() -> None:
    COST_DIR.mkdir(parents=True, exist_ok=True)
    # ATR5m thật từ dữ liệu M5 đã tải
    m5 = pd.read_parquet(DATA_DIR / f"{SYMBOL}_5m.parquet")
    tr = np.maximum(m5["high"] - m5["low"],
                    np.maximum(abs(m5["high"] - m5["close"].shift()),
                               abs(m5["low"] - m5["close"].shift())))
    atr5m = float(tr.rolling(14 * 12).mean().median())
    logger.info(f"ATR5m median (USDT): {atr5m:.4f}")

    end = date(2026, 9, 18)
    days = [end - timedelta(days=i) for i in range(N_DAYS)]
    hourly_all, size_all, stop_infos = [], [], []
    for d in days:
        p = download_daily_agg(d.isoformat())
        if p is None:
            logger.warning(f"Không có aggTrades {d}")
            continue
        h, s, info = process_day(p, atr5m)
        h["date"] = d.isoformat()
        hourly_all.append(h)
        size_all.append(s)
        stop_infos.append(info)
        logger.info(f"{d}: ok")

    hourly = pd.concat(hourly_all).groupby("hour", as_index=False).agg(
        roll_spread_bps=("roll_spread_bps", "median"),
        quote_volume=("quote_volume", "mean"),
        n_trades=("n_trades", "mean"))
    size = pd.concat(size_all).groupby("bucket_mid_notional", as_index=False).agg(
        impact_5s_bps_abs=("impact_5s_bps_abs", "mean"), n=("n", "sum"))
    hourly.to_parquet(COST_DIR / "slippage_hourly.parquet", index=False)
    size.to_parquet(COST_DIR / "slippage_size_impact.parquet", index=False)

    # Hệ số slippage-lúc-stop = median burst multiplier qua các ngày (fallback 1.5 như V1)
    mults = [info["burst_mult"] for info in stop_infos if info["burst_mult"] == info["burst_mult"]]
    stop_mult = float(np.median(mults)) if mults else 1.5

    summary = {
        "window_days": N_DAYS,
        "atr5m_usdt": atr5m,
        "roll_spread_bps_by_hour": {int(r.hour): round(float(r.roll_spread_bps), 2)
                                    for r in hourly.itertuples() if r.roll_spread_bps == r.roll_spread_bps},
        "median_roll_spread_bps": round(float(hourly["roll_spread_bps"].median()), 2),
        "size_impact_5s_bps_abs": {f"Q{i+1}": round(float(v), 2)
                                   for i, v in enumerate(size["impact_5s_bps_abs"][:5])},
        "stop_slippage_multiplier_measured": round(stop_mult, 2),
        "note": "V1 dùng stop_slippage_multiplier=1.5 (giả định) — V2 đo được trên aggTrades thật",
    }
    (COST_DIR / "cost_calibration_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Done. median spread {summary['median_roll_spread_bps']} bps, "
                f"stop multiplier {summary['stop_slippage_multiplier_measured']}")


if __name__ == "__main__":
    main()
