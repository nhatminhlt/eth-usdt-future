"""Build dataset enriched: M5 + indicators + patterns + taker flow + levels + state.

Chạy: .venv/Scripts/python.exe scripts/build_dataset.py
Output: data/SOLUSDT_5m_enriched.parquet — nền cho event-study (M2.5) và backtest (M3+).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.data.resample import adr20, resample, to_utc_index
from solfut.features import indicators as ind
from solfut.features import levels as lvl
from solfut.features import orderflow as of
from solfut.features import patterns as pat
from solfut.features import state as st

SYMBOL = "SOLUSDT"


def main() -> None:
    m5 = pd.read_parquet(DATA_DIR / f"{SYMBOL}_5m.parquet")
    m5 = to_utc_index(m5)
    logger.info(f"M5 {len(m5)} bars")

    # ADR20 từ D1 (đã tải) — ffill về M5
    d1_raw = pd.read_parquet(DATA_DIR / f"{SYMBOL}_1d.parquet")
    d1 = resample(to_utc_index(d1_raw), "1D")
    adr20_s = adr20(d1)

    df = ind.add_indicators(m5)
    logger.info("indicators done")
    df = pat.add_patterns(df)
    df = of.add_taker_flow(df)
    df = lvl.add_round_levels(df)
    df = lvl.add_prev_day_levels(df, d1)
    logger.info("patterns/flow/levels done")
    df = st.add_state(df, adr20_s)
    logger.info("state done")

    out = DATA_DIR / f"{SYMBOL}_5m_enriched.parquet"
    df.to_parquet(out)
    logger.info(f"Saved {len(df)} rows → {out.name}")


if __name__ == "__main__":
    main()
