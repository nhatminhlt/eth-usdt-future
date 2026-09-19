"""Tải 5m klines cho cross-symbol replication: ETHUSDT, DOGEUSDT, AVAXUSDT — TRAIN window
2020-10 → 2023-08 (+2 tháng label buffer). KHÔNG tải VAL/OOS (kỷ luật: chưa cần).

Chạy: .venv/Scripts/python.exe scripts/download_cross_symbols.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader

SYMBOLS = ["ETHUSDT", "DOGEUSDT", "AVAXUSDT"]
MONTHS = downloader.month_list("2020-10", "2023-08")


def main() -> None:
    for sym in SYMBOLS:
        got = 0
        for m in MONTHS:
            if downloader.download_monthly_klines(sym, "5m", m) is not None:
                got += 1
        logger.info(f"{sym}: {got}/{len(MONTHS)} tháng có dữ liệu")


if __name__ == "__main__":
    main()
