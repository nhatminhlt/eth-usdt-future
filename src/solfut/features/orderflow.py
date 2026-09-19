"""Order-flow features (PLAN M2.5): taker imbalance + CVD từ trường taker_buy_volume
trong klines (miễn phí full history); OI từ metrics data.binance.vision.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from solfut.data.downloader import DATA_DIR


def add_taker_flow(m5: pd.DataFrame, win_fast: int = 12, win_slow: int = 72) -> pd.DataFrame:
    """Imbalance = (2×taker_buy_vol − vol) / vol, rolling; CVD = cumsum signed vol."""
    out = m5.copy()
    signed = 2 * out["taker_buy_volume"] - out["volume"]
    denom = out["volume"].replace(0, np.nan)
    out["taker_imbalance_1h"] = signed.rolling(win_slow).sum() / (out["volume"].rolling(win_slow).sum().replace(0, np.nan))
    out["taker_imbalance_fast"] = signed.rolling(win_fast).sum() / (out["volume"].rolling(win_fast).sum().replace(0, np.nan))
    out["cvd"] = signed.cumsum()
    out["cvd_slope_1h"] = out["cvd"].diff(win_slow)
    return out


def load_oi(symbol: str = "SOLUSDT") -> pd.DataFrame:
    """Ghép metrics daily parquet → chuỗi OI 5m (create_time UTC index)."""
    d = DATA_DIR / "metrics" / symbol
    files = sorted(d.glob(f"{symbol}-metrics-*.parquet"))
    if not files:
        raise FileNotFoundError(f"Chưa tải metrics cho {symbol} — chạy scripts/download_extras.py")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df = df.drop_duplicates(subset="create_time").sort_values("create_time").set_index("create_time")
    df["sum_open_interest"] = df["sum_open_interest"].astype("float64")
    return df[["sum_open_interest"]]


def add_oi_context(m5: pd.DataFrame, oi: pd.DataFrame) -> pd.DataFrame:
    """ΔOI 1h + phân loại 4 góc phần tư (OI↑giá↑ = tiền mới long...). Shift OI để tránh lookahead."""
    out = m5.copy()
    oi_shift = oi["sum_open_interest"].shift(1)
    joined = out.join(oi_shift.rename("oi"), how="left")
    joined["oi"] = joined["oi"].ffill(limit=12)  # tối đa 1 giờ
    out["oi"] = joined["oi"]
    out["oi_delta_1h"] = joined["oi"].diff(12)
    price_delta_1h = out["close"].diff(12)
    up = out["oi_delta_1h"] > 0
    out["oi_quadrant"] = pd.Series(pd.NA, index=out.index, dtype="object")
    out.loc[up & (price_delta_1h > 0), "oi_quadrant"] = "oi_up_price_up"
    out.loc[up & (price_delta_1h <= 0), "oi_quadrant"] = "oi_up_price_down"
    out.loc[~up & (price_delta_1h > 0), "oi_quadrant"] = "oi_down_price_up"
    out.loc[~up & (price_delta_1h <= 0), "oi_quadrant"] = "oi_down_price_down"
    return out
