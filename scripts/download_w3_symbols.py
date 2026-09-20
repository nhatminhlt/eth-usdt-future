"""W3 — tải 5m BNB/XRP/ADA/LINK 2020-10→2024-07 (TRAIN+VAL) cho replication + ensemble.
Chạy: .venv/Scripts/python.exe scripts/download_w3_symbols.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader

SYMBOLS = ["BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
MONTHS = downloader.month_list("2020-10", "2024-07")


def main() -> None:
    for sym in SYMBOLS:
        got = sum(1 for m in MONTHS if downloader.download_monthly_klines(sym, "5m", m))
        logger.info(f"{sym}: {got}/{len(MONTHS)} tháng")


if __name__ == "__main__":
    main()
