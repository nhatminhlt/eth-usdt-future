"""W7 — tải 5m ATOM/DOT/LTC/EOS 2020-10→2026-08 cho replication + ensemble-12.
Kiểm tra listing date qua exchangeInfo trước (skip nếu listing sau 2020-10).
Chạy: .venv/Scripts/python.exe scripts/download_w7_symbols.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader
from solfut.data.binance_client import BinanceFuturesPublic

CANDIDATES = ["ATOMUSDT", "DOTUSDT", "LTCUSDT", "EOSUSDT"]


def main() -> None:
    client = BinanceFuturesPublic()
    info = client.exchange_info()
    od = {s["symbol"]: s.get("onboardDate") for s in info["symbols"]}
    months = downloader.month_list("2020-10", "2026-08")
    for sym in CANDIDATES:
        listed = datetime.datetime.utcfromtimestamp(od[sym] / 1000).date() if od.get(sym) else None
        if listed and listed > datetime.date(2020, 10, 1):
            logger.warning(f"{sym}: listing {listed} — sau 2020-10, SKIP")
            continue
        got = sum(1 for m in months if downloader.download_monthly_klines(sym, "5m", m))
        logger.info(f"{sym} (listing {listed}): {got}/{len(months)} tháng")


if __name__ == "__main__":
    main()
