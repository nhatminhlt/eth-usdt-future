"""Orchestrator tải dữ liệu SOLUSDT (M1).

Chạy: .venv/Scripts/python.exe scripts/download_data.py
- M5 monthly bulk 2020-09 → tháng trước của tháng hiện tại, rồi REST lấp phần gần nhất
- H1, D1 tương tự
- Funding history full + interval động từ fundingInfo
- Quality gate toàn bộ, lưu report
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.binance_client import BinanceFuturesPublic
from solfut.data import downloader, funding as fmod, quality
from solfut.data.resample import resample, to_utc_index

SYMBOL = "SOLUSDT"
START = "2020-09"


def main() -> None:
    client = BinanceFuturesPublic()
    client.ping()
    logger.info("API OK")

    specs = client.symbol_filters(SYMBOL)
    logger.info(f"Specs: {specs}")
    interval_h = fmod.funding_interval_hours(client, SYMBOL)
    logger.info(f"Funding interval hiện hành (fundingInfo): {interval_h}h")

    now = datetime.now(timezone.utc)
    last_complete = f"{now.year:04d}-{now.month - 1:02d}" if now.month > 1 else f"{now.year - 1:04d}-12"
    months = downloader.month_list(START, last_complete)
    logger.info(f"Monthly range: {months[0]} → {months[-1]} ({len(months)} tháng)")

    for interval in ("5m", "1h", "1d"):
        for m in months:
            downloader.download_monthly_klines(SYMBOL, interval, m)

        df = downloader.load_monthlies(SYMBOL, interval)
        df = quality.ohlc_columns_float(df)
        minutes = {"5m": 5, "1h": 60, "1d": 1440}[interval]
        clean, report = quality.check_klines(df, minutes, name=f"{SYMBOL}_{interval}")
        clean.to_parquet(downloader.DATA_DIR / f"{SYMBOL}_{interval}.parquet", index=False)

        # REST lấp phần từ cuối monthly tới hiện tại
        tail_start = int(clean["open_time"].iloc[-1]) + 1
        tail = downloader.fetch_recent_klines(client, SYMBOL, interval, tail_start)
        if len(tail):
            logger.info(f"REST tail {interval}: {len(tail)} nến mới")
            both = pd.concat([clean, tail.drop(columns=["ignore"], errors="ignore")], ignore_index=True)
            both = both.drop_duplicates(subset="open_time", keep="first").sort_values("open_time")
            both, _ = quality.check_klines(both, minutes, name=f"{SYMBOL}_{interval}_tail")
            both.to_parquet(downloader.DATA_DIR / f"{SYMBOL}_{interval}.parquet", index=False)

    # Funding
    start_ms = int(datetime(2020, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
    fdf = fmod.download_funding(client, SYMBOL, start_ms)
    logger.info(f"Funding stats: {fmod.funding_stats(fdf)}")

    # Kiểm tra chéo: resample M5 → H1/D1 khớp nguồn không (sanity)
    m5 = quality.ohlc_columns_float(pd.read_parquet(downloader.DATA_DIR / f"{SYMBOL}_5m.parquet"))
    m5i = to_utc_index(m5)
    h1 = resample(m5i, "1h")
    d1 = resample(m5i, "1D")
    logger.info(f"Resample sanity: M5 {len(m5)} → H1 {len(h1)} → D1 {len(d1)}")


if __name__ == "__main__":
    main()
