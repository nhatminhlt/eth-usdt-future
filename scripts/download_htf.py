"""Tải klines HTF (15m + 1h + 4h + 1d) monthly bulk cho 1+ symbol — nền chuyển-base sau NO-GO.

4h/15m có sẵn monthly zip trên vision (probe 200). Funding không nằm ở đây: dùng
scripts/download_funding_vision.py (REST fapi bị geo-block 451 ở máy này; funding
ETH/SOL đã có sẵn).

Chạy: .venv/Scripts/python.exe scripts/download_htf.py ETHUSDT BTCUSDT
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader

START = "2020-09"
END = "2026-08"


def main() -> None:
    symbols = sys.argv[1:] or ["ETHUSDT"]
    for sym in symbols:
        months = downloader.month_list(START, END)
        for interval in ("15m", "1h", "4h", "1d"):
            got = sum(1 for m in months if downloader.download_monthly_klines(sym, interval, m))
            merged = downloader.load_monthlies(sym, interval)
            merged.to_parquet(downloader.DATA_DIR / f"{sym}_{interval}.parquet", index=False)
            logger.info(f"{sym} {interval}: {got}/{len(months)} tháng → {len(merged)} nến (file đơn)")


if __name__ == "__main__":
    main()
