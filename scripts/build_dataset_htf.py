"""Build enriched HTF (15m + 1h + 4h + 1d) cho chuyển-base — composition GIỐNG
build_dataset_w9.py.

Khác biệt so với 5m build (đổi nền theo user sau NO-GO):
- Nguồn: 1h/1d monthlies; D1 tham chiếu = file 1d THẬT (không resample).
- Round levels theo quy mô giá từng symbol (10/5 của SOL degenerate ở giá cao —
  event study tính near-round theo khoảng cách tương đối 0.15% giá).
- add_taker_flow giữ nguyên bars (12/72) — cờ state (tight_tr/barbwire 20/8 bar)
  giữ nguyên bar-count: ý nghĩa wall-clock khác 5m, PHẢI re-derive khi đặt giả
  thuyết mới trên nền này (không tune ngầm — bài học 23).

Chạy: .venv/Scripts/python.exe scripts/build_dataset_htf.py ETHUSDT BTCUSDT
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.data.resample import to_utc_index
from solfut.features import indicators as ind
from solfut.features import levels as lvl
from solfut.features import orderflow as of
from solfut.features import patterns as pat
from solfut.features import state as st

NUM_COLS = ("open", "high", "low", "close", "volume", "quote_volume",
            "taker_buy_volume", "taker_buy_quote_volume")

# Bước round number theo quy mô giá (giá điển hình từng symbol, lịch sử 2020→2026)
ROUND_STEPS = {
    "SOLUSDT": (10.0, 5.0),     # ~$20–290
    "BTCUSDT": (1000.0, 100.0), # ~$10k–125k
    "ETHUSDT": (100.0, 10.0),   # ~$300–4800
}
DEFAULT_STEPS = (100.0, 10.0)


def _load_tf(symbol: str, interval: str) -> pd.DataFrame:
    df = load_monthlies(symbol, interval)
    df = to_utc_index(df)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def enrich(df: pd.DataFrame, d1: pd.DataFrame, steps: tuple[float, float]) -> pd.DataFrame:
    df = ind.add_indicators(df)
    logger.info("indicators done")
    df = pat.add_patterns(df)
    df = of.add_taker_flow(df)
    df = lvl.add_round_levels(df, step_large=steps[0], step_small=steps[1])
    df = lvl.add_prev_day_levels(df, d1)
    logger.info("patterns/flow/levels done")
    adr20_s = (d1["high"] - d1["low"]).rolling(20).mean()
    df = st.add_state(df, adr20_s)
    logger.info("state done")
    return df


def main() -> None:
    symbols = sys.argv[1:] or ["ETHUSDT"]
    for symbol in symbols:
        steps = ROUND_STEPS.get(symbol, DEFAULT_STEPS)
        d1 = _load_tf(symbol, "1d")
        logger.info(f"{symbol} D1 {len(d1)} bars")

        for interval in ("15m", "1h", "4h", "1d"):
            tf = _load_tf(symbol, interval)
            logger.info(f"{symbol} {interval.upper()} {len(tf)} bars")
            out = DATA_DIR / f"{symbol}_{interval}_enriched.parquet"
            enrich(tf, d1, steps).to_parquet(out)
            logger.info(f"{symbol} saved {out.name}")


if __name__ == "__main__":
    main()
