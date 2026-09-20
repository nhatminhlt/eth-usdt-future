"""W5 — tải OOS2 months (2025-10→2026-08) cho 7 symbol (SOL đã có đủ). CHUẨN BỊ cho
one-shot OOS2 — KHÔNG chạy backtest trong script này.
Chạy: .venv/Scripts/python.exe scripts/download_oos2_months.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader

SYMBOLS = ["ETHUSDT", "DOGEUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
MONTHS = downloader.month_list("2025-10", "2026-08")


def main() -> None:
    for sym in SYMBOLS:
        got = sum(1 for m in MONTHS if downloader.download_monthly_klines(sym, "5m", m))
        logger.info(f"{sym}: {got}/{len(MONTHS)} tháng OOS2")


if __name__ == "__main__":
    main()
