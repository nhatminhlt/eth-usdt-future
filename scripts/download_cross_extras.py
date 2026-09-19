"""Tải funding history + VAL 5m (2023-07→2024-07 + buffer) cho ETH/DOGE/AVAX — phục vụ
portfolio backtest H2b 4 symbol. Chạy: .venv/Scripts/python.exe scripts/download_cross_extras.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loguru import logger

from solfut.data import downloader
from solfut.data.binance_client import BinanceFuturesPublic

SYMBOLS = ["ETHUSDT", "DOGEUSDT", "AVAXUSDT"]


def main() -> None:
    client = BinanceFuturesPublic()
    client.ping()
    val_months = downloader.month_list("2023-07", "2024-07")
    for sym in SYMBOLS:
        got = sum(1 for m in val_months if downloader.download_monthly_klines(sym, "5m", m))
        logger.info(f"{sym} VAL: {got}/{len(val_months)} tháng")
        # funding history full (REST, ít records)
        fdf = downloader.fetch_funding_history(client, sym, start_ms=1600128000000)  # 2020-09
        out = downloader.DATA_DIR / "funding" / f"{sym}_funding.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        fdf.to_parquet(out, index=False)
        logger.info(f"{sym} funding: {len(fdf)} kỳ → {out.name}")


if __name__ == "__main__":
    main()
