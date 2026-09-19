"""Funding history + interval động (luật 17 — không hardcode 8h)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from .binance_client import BinanceFuturesPublic
from .downloader import DATA_DIR

FUNDING_DIR = DATA_DIR / "funding"


def funding_interval_hours(client: BinanceFuturesPublic, symbol: str, default: int = 8) -> int:
    """Đọc interval hiện hành. SOLUSDT vắng trong fundingInfo = mặc định 8h."""
    return client.funding_interval_hours(symbol, default=default)


def download_funding(client: BinanceFuturesPublic, symbol: str, start_ms: int) -> pd.DataFrame:
    FUNDING_DIR.mkdir(parents=True, exist_ok=True)
    rows = client.funding_rate_all(symbol, start_ms)
    df = pd.DataFrame(rows)
    out = df[["fundingTime", "fundingRate"]].copy()
    out["fundingTime"] = out["fundingTime"].astype("int64")
    out["fundingRate"] = out["fundingRate"].astype("float64")
    path = FUNDING_DIR / f"{symbol}_funding.parquet"
    out.to_parquet(path, index=False)
    logger.info(f"Funding: {len(out)} kỳ từ {datetime.fromtimestamp(out['fundingTime'].iloc[0]/1000, tz=timezone.utc)} → {path.name}")
    return out


def load_funding(symbol: str) -> pd.DataFrame:
    return pd.read_parquet(FUNDING_DIR / f"{symbol}_funding.parquet")


def funding_stats(df: pd.DataFrame) -> dict:
    r = df["fundingRate"]
    return {
        "n": len(r), "mean": float(r.mean()), "median": float(r.median()),
        "min": float(r.min()), "max": float(r.max()),
        "pct_positive": float((r > 0).mean()),
    }
