"""Tải dữ liệu bổ sung cho M2 context/orderflow: BTCUSDT D1 (trend filter) +
metrics SOLUSDT (OI 5m) full history. Chạy nền 15–25 phút.

Chạy: .venv/Scripts/python.exe scripts/download_extras.py
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader

SYMBOL = "SOLUSDT"
START = "2020-09"


def main() -> None:
    # BTC D1 (monthly — nhẹ)
    months = downloader.month_list(START, "2026-08")
    for m in months:
        downloader.download_monthly_klines("BTCUSDT", "1d", m)
    btc = downloader.load_monthlies("BTCUSDT", "1d")
    btc.to_parquet(downloader.DATA_DIR / "BTCUSDT_1d.parquet", index=False)
    logger.info(f"BTCUSDT D1: {len(btc)} nến")

    # Metrics SOLUSDT (daily, OI 5m) — full history
    d0 = date(2020, 9, 14)
    d1 = date(2026, 9, 18)
    n_ok, n_miss = 0, 0
    d = d0
    while d <= d1:
        p = downloader.download_daily_metrics(SYMBOL, d.isoformat())
        if p:
            n_ok += 1
        else:
            n_miss += 1
        d += timedelta(days=1)
        if (n_ok + n_miss) % 100 == 0:
            logger.info(f"metrics progress: {n_ok + n_miss} ngày (miss {n_miss})")
        time.sleep(0.05)
    logger.info(f"Metrics done: ok {n_ok}, miss {n_miss}")


if __name__ == "__main__":
    main()
