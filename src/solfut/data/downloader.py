"""Tải dữ liệu SOLUSDT: bulk monthly zip từ data.binance.vision + REST cho phần gần nhất.

Lưu ý định dạng data.binance.vision (futures/um):
- Klines monthly zip: CSV có/không có header tùy năm → detect khi đọc.
- open_time: ms ở dữ liệu cũ; từ 2025-01 Binance chuyển sang MICROseconds ở một số dataset
  → chuẩn hóa: nếu > 1e14 thì chia 1000 về ms. Mọi parquet lưu统一 ms.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

from .binance_client import BinanceFuturesPublic, KLINE_COLUMNS

VISION = "https://data.binance.vision/data/futures/um"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def download_daily_metrics(symbol: str, date_iso: str, cache_dir: Path | None = None) -> Path | None:
    """metrics hàng ngày (OI + long-short ratio, granular 5m) từ data.binance.vision."""
    cache_dir = cache_dir or (DATA_DIR / "metrics" / symbol)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{symbol}-metrics-{date_iso}.parquet"
    if out.exists():
        return out
    url = f"{VISION}/daily/metrics/{symbol}/{symbol}-metrics-{date_iso}.zip"
    r = requests.get(url, timeout=60)
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
    df = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=header)
    df.to_parquet(out, index=False)
    return out


def month_list(start: str, end: str) -> list[str]:
    """'2020-09' .. '2026-09' (bao gồm cả 2 đầu)."""
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _normalize_open_time(df: pd.DataFrame) -> pd.DataFrame:
    df["open_time"] = df["open_time"].astype("int64")
    if df["open_time"].iloc[0] > 1e14:  # microseconds → ms
        df["open_time"] = (df["open_time"] // 1000).astype("int64")
    if "close_time" in df:
        df["close_time"] = df["close_time"].astype("int64")
        if df["close_time"].iloc[0] > 1e14:
            df["close_time"] = (df["close_time"] // 1000).astype("int64")
    return df


def download_monthly_klines(symbol: str, interval: str, month: str,
                            cache_dir: Path | None = None) -> Path | None:
    """Tải 1 monthly zip → parquet. Trả về None nếu tháng chưa tồn tại (404)."""
    cache_dir = cache_dir or (DATA_DIR / "klines" / interval)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{symbol}-{interval}-{month}.parquet"
    if out.exists():
        return out
    url = f"{VISION}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        logger.warning(f"404 (chưa có) {url}")
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        raw = z.read(name).decode("utf-8")
    lines = raw.strip().split("\n")
    # detect header: dòng đầu không parse được số
    header = None
    try:
        float(lines[0].split(",")[0])
    except ValueError:
        header = lines[0].split(",")
        lines = lines[1:]
    cols = header if header and len(header) == 12 else KLINE_COLUMNS
    df = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=cols)
    df = _normalize_open_time(df)
    df.to_parquet(out, index=False)
    logger.info(f"{symbol} {interval} {month}: {len(df)} bars → {out.name}")
    return out


def load_monthlies(symbol: str, interval: str) -> pd.DataFrame:
    files = sorted((DATA_DIR / "klines" / interval).glob(f"{symbol}-{interval}-*.parquet"))
    if not files:
        raise FileNotFoundError(f"Chưa tải dữ liệu {symbol} {interval}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.drop(columns=["ignore"], errors="ignore")  # cột rác, dtype trộn giữa các tháng
    df = df.drop_duplicates(subset="open_time", keep="first").sort_values("open_time")
    return df.reset_index(drop=True)


def fetch_recent_klines(client: BinanceFuturesPublic, symbol: str, interval: str,
                        start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
    """Phần gần nhất chưa có monthly zip — paginate REST (1500/req)."""
    end_ms = end_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    out, cursor = [], start_ms
    while cursor < end_ms:
        batch = client.klines(symbol, interval, start_ms=cursor, end_ms=end_ms)
        if not batch:
            break
        out.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 1500:
            break
        import time; time.sleep(0.15)
    df = pd.DataFrame(out, columns=KLINE_COLUMNS)
    df = _normalize_open_time(df)
    for c in ("open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_volume", "taker_buy_quote_volume"):
        df[c] = df[c].astype("float64")
    df["count"] = df["count"].astype("int64")
    return df


def fetch_funding_history(client: BinanceFuturesPublic, symbol: str, start_ms: int) -> pd.DataFrame:
    rows = client.funding_rate_all(symbol, start_ms)
    df = pd.DataFrame(rows)
    df["fundingTime"] = df["fundingTime"].astype("int64")
    df["fundingRate"] = df["fundingRate"].astype("float64")
    return df[["fundingTime", "fundingRate", "markPrice" if "markPrice" in df else "fundingRate"]]
