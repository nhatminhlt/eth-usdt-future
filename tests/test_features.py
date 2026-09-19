"""Test chống lookahead + test indicators/patterns/sessions.

Nguyên tắc lookahead: mọi feature tại bar t phải GIỐNG NHAU khi tính trên df đầy đủ
hoặc df cắt tại t (đặc tính causal). Test trên dữ liệu thật SOLUSDT M5 (nếu có) + synthetic.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from solfut.features.indicators import add_indicators
from solfut.features.patterns import add_patterns
from solfut.features.levels import add_round_levels, add_swing_levels
from solfut.features.orderflow import add_taker_flow
from solfut.features.sessions import activity_mask, load_news_calendar

DATA = Path(__file__).resolve().parents[1] / "data"


def load_m5(n: int = 5000) -> pd.DataFrame:
    p = DATA / "SOLUSDT_5m.parquet"
    if not p.exists():
        pytest.skip("Chưa tải dữ liệu M5")
    df = pd.read_parquet(p).tail(n).reset_index(drop=True)
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def make_synthetic(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-02", periods=n, freq="5min", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 0.2, n))
    high = close + np.abs(rng.normal(0.1, 0.05, n))
    low = close - np.abs(rng.normal(0.1, 0.05, n))
    open_ = low + (high - low) * rng.random(n)
    vol = rng.uniform(1, 10, n)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": vol, "quote_volume": vol * close,
                       "count": 100, "taker_buy_volume": vol / 2,
                       "taker_buy_quote_volume": vol * close / 2}, index=idx)
    return df


CAUSAL_OUTPUTS = ["ema13", "ema20", "ema25", "atr14", "rsi14", "adx14", "macd",
                  "macd_signal", "mom12", "kc_mid", "bb_mid"]


def test_indicators_no_lookahead():
    df = load_m5()
    full = add_indicators(df)
    cut = len(df) // 2
    part = add_indicators(df.iloc[:cut].copy())
    for col in CAUSAL_OUTPUTS:
        np.testing.assert_allclose(full[col].iloc[:cut].values, part[col].values,
                                   rtol=1e-10, atol=1e-10, err_msg=f"lookahead ở {col}")


def test_patterns_no_lookahead():
    df = add_indicators(load_m5())
    full = add_patterns(df)
    cut = len(df) // 2
    part = add_patterns(df.iloc[:cut].copy())
    for col in full.columns:
        if full[col].dtype == bool:
            np.testing.assert_array_equal(full[col].iloc[:cut].values, part[col].values,
                                          err_msg=f"lookahead ở pattern {col}")


def test_taker_flow_no_lookahead():
    df = load_m5()
    full = add_taker_flow(df)
    cut = len(df) // 2
    part = add_taker_flow(df.iloc[:cut].copy())
    for col in ("taker_imbalance_1h", "taker_imbalance_fast", "cvd"):
        np.testing.assert_allclose(full[col].iloc[:cut].values, part[col].values,
                                   rtol=1e-10, err_msg=f"lookahead ở {col}")


def test_round_levels_use_prev_close():
    df = make_synthetic()
    out = add_round_levels(df)
    # round_below tại bar t phải dựa trên close[t−1]
    t = 10
    prev_close = df["close"].iloc[t - 1]
    step = 10.0 if prev_close >= 50 else 5.0
    assert out["round_below"].iloc[t] == np.floor(prev_close / step) * step


def test_swing_levels_only_confirmed():
    df = make_synthetic(300)
    out = add_swing_levels(df, k=12)
    # Swing xác nhận tại bar t cần bar (i+12) — tại t < 12 không có swing nào
    assert out["swing_high_conf"].iloc[:12].isna().all()


def test_activity_mask_blocks_news_and_window():
    idx = pd.date_range("2026-09-15 00:00", periods=288, freq="5min", tz="UTC")  # thứ Ba
    news = pd.DataFrame({"ts_utc": pd.to_datetime(["2026-09-15 14:00:00+00:00"])})
    mask = activity_mask(idx, news=news, funding_interval_hours=None)
    t_news = idx.get_indexer([pd.Timestamp("2026-09-15 14:00", tz="UTC")])[0]
    # trong window 12:00–21:00 → True, nhưng blackout ±30' quanh 14:00 → False
    assert not mask[t_news]
    t_in = idx.get_indexer([pd.Timestamp("2026-09-15 15:00", tz="UTC")])[0]
    assert mask[t_in]
    # ngoài window (06:00) → False
    t_out = idx.get_indexer([pd.Timestamp("2026-09-15 06:00", tz="UTC")])[0]
    assert not mask[t_out]
    # 10h → skip
    t_skip = idx.get_indexer([pd.Timestamp("2026-09-15 10:30", tz="UTC")])[0]
    assert not mask[t_skip]


def test_activity_mask_funding_blackout():
    idx = pd.date_range("2026-09-15 00:00", periods=288, freq="5min", tz="UTC")
    mask = activity_mask(idx, funding_interval_hours=8)
    # mốc funding 16:00 nằm trong window 12:00–21:00
    t_fund = idx.get_indexer([pd.Timestamp("2026-09-15 16:00", tz="UTC")])[0]
    assert not mask[t_fund]
    t_ok = idx.get_indexer([pd.Timestamp("2026-09-15 16:30", tz="UTC")])[0]
    assert mask[t_ok]


def test_news_calendar_loads():
    cal = load_news_calendar()
    assert {"date_utc", "time_utc", "event", "ts_utc"} <= set(cal.columns)
    assert len(cal) > 200
