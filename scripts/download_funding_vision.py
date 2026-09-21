"""Tải funding rate monthly bulk cho 1 symbol từ data.binance.vision.

REST fapi.binance.com bị geo-block 451 ở máy này → funding dùng archive
data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip.

Chạy: .venv/Scripts/python.exe scripts/download_funding_vision.py BTCUSDT
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import requests
from loguru import logger

from solfut.data import downloader
from solfut.data.funding import FUNDING_DIR

VISION = downloader.VISION


def download_funding_month(symbol: str, month: str) -> pd.DataFrame | None:
    url = f"{VISION}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8")
    lines = raw.strip().split("\n")
    header = None
    try:
        float(lines[0].split(",")[0])
    except ValueError:
        header = lines[0].split(",")
        lines = lines[1:]
    cols = header or ["calc_time", "funding_interval_hours", "last_funding_rate"]
    df = pd.read_csv(io.StringIO("\n".join(lines)), header=None, names=cols)
    return df


def fetch_funding_vision(symbol: str, start: str, end: str) -> pd.DataFrame:
    parts = []
    for m in downloader.month_list(start, end):
        df = download_funding_month(symbol, m)
        if df is not None:
            parts.append(df)
    if not parts:
        raise FileNotFoundError(f"Không có funding archive nào cho {symbol}")
    full = pd.concat(parts, ignore_index=True)
    # Chuẩn hóa về schema funding hiện có: fundingTime (ms), fundingRate
    tcol = "calc_time" if "calc_time" in full.columns else full.columns[0]
    full["fundingTime"] = pd.to_numeric(full[tcol], errors="coerce")
    if full["fundingTime"].iloc[0] > 1e14:  # microseconds → ms
        full["fundingTime"] = (full["fundingTime"] // 1000).astype("int64")
    full["fundingTime"] = full["fundingTime"].astype("int64")
    rcol = "last_funding_rate" if "last_funding_rate" in full.columns else full.columns[-1]
    full["fundingRate"] = pd.to_numeric(full[rcol], errors="coerce").astype("float64")
    full = full.drop_duplicates(subset="fundingTime").sort_values("fundingTime")
    return full[["fundingTime", "fundingRate"]].reset_index(drop=True)


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    start = sys.argv[2] if len(sys.argv) > 2 else "2019-09"
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-08"
    fdf = fetch_funding_vision(symbol, start, end)
    FUNDING_DIR.mkdir(parents=True, exist_ok=True)
    out = FUNDING_DIR / f"{symbol}_funding.parquet"
    fdf.to_parquet(out, index=False)
    logger.info(f"{symbol} funding: {len(fdf)} kỳ → {out.name}")


if __name__ == "__main__":
    main()
