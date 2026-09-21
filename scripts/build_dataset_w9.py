"""W9 — build enriched 5m cho BTCUSDT/ETHUSDT (composition GIỐNG build_dataset.py).
ETH không có file 1d → D1 resample trực tiếp từ 5m (ADR20 + prev-day levels cùng nguồn).

Chạy: .venv/Scripts/python.exe scripts/build_dataset_w9.py BTCUSDT ETHUSDT
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.data.resample import adr20, resample, to_utc_index
from solfut.features import indicators as ind
from solfut.features import levels as lvl
from solfut.features import orderflow as of
from solfut.features import patterns as pat
from solfut.features import state as st


def build(symbol: str) -> None:
    m5 = load_monthlies(symbol, "5m")
    m5 = to_utc_index(m5)
    for c in ("open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_volume", "taker_buy_quote_volume"):
        m5[c] = pd.to_numeric(m5[c], errors="coerce")
    logger.info(f"{symbol} M5 {len(m5)} bars")

    d1 = resample(m5, "1D")
    adr20_s = adr20(d1)

    df = ind.add_indicators(m5)
    logger.info(f"{symbol} indicators done")
    df = pat.add_patterns(df)
    df = of.add_taker_flow(df)
    df = lvl.add_round_levels(df)
    df = lvl.add_prev_day_levels(df, d1)
    logger.info(f"{symbol} patterns/flow/levels done")
    df = st.add_state(df, adr20_s)
    logger.info(f"{symbol} state done")

    out = DATA_DIR / f"{symbol}_5m_enriched.parquet"
    df.to_parquet(out)
    logger.info(f"{symbol} saved {len(df)} rows → {out.name}")


if __name__ == "__main__":
    for sym in sys.argv[1:]:
        build(sym)
