"""Unit test quality gate + resample — dữ liệu tổng hợp, biết trước kết quả đúng."""
import numpy as np
import pandas as pd
import pytest

from solfut.data.quality import check_klines
from solfut.data.resample import adr20, daily_pivots, resample, round_levels, to_utc_index


def make_df(rows):
    cols = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "count", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore"]
    return pd.DataFrame(rows, columns=cols)


def test_quality_flags_ohlc_violation():
    base = 1_700_000_000_000
    rows = [
        [base + i * 300_000, 100, 102, 99, 101, 1, 0, 1, 10, 0.5, 0.5, 0]
        for i in range(5)
    ]
    rows.append([base + 5 * 300_000, 100, 90, 99, 101, 1, 0, 1, 10, 0.5, 0.5, 0])  # high < close → lỗi
    df = make_df(rows)
    clean, report = check_klines(df, 5, name="test_ohlc")
    assert report["ohlc_violations"] == 1
    assert len(clean) == 5


def test_quality_dedupes():
    base = 1_700_000_000_000
    row = [base, 100, 102, 99, 101, 1, 0, 1, 10, 0.5, 0.5, 0]
    df = make_df([row, row, [base + 300_000] + row[1:]])
    clean, report = check_klines(df, 5, name="test_dup")
    assert report["duplicates"] == 1
    assert len(clean) == 2


def test_resample_m5_to_h1_and_d1():
    base = pd.Timestamp("2024-01-02 00:00", tz="UTC")  # thứ Ba — có phiên đủ
    times = [base + pd.Timedelta(minutes=5 * i) for i in range(288)]  # đúng 1 ngày M5
    df = pd.DataFrame({
        "open_time": [int(t.timestamp() * 1000) for t in times],
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": 1.0, "quote_volume": 100.0, "count": 10,
        "taker_buy_volume": 0.5, "taker_buy_quote_volume": 50.0,
    }, index=pd.DatetimeIndex(times))
    df = to_utc_index(df)
    h1 = resample(df, "1h")
    d1 = resample(df, "1D")
    assert len(h1) == 24
    assert len(d1) == 1
    assert d1["high"].iloc[0] == 101.0 and d1["low"].iloc[0] == 99.0
    assert d1["volume"].iloc[0] == pytest.approx(288.0)


def test_adr20_and_pivots():
    times = pd.date_range("2024-01-01", periods=25, freq="1D", tz="UTC")
    d1 = pd.DataFrame({"open": 100, "high": 110, "low": 100, "close": 105}, index=times)
    a = adr20(d1)
    assert a.iloc[-1] == pytest.approx(10.0)  # 24 giá trị range=10 đầy đủ
    pv = daily_pivots(d1)
    assert pv["pivot"].iloc[0] == pytest.approx((110 + 100 + 105) / 3)


def test_round_levels_step_switch():
    assert round_levels(111.54)["step"] == 10.0
    assert round_levels(111.54)["below"] == 110.0
    assert round_levels(43.21)["step"] == 5.0
    assert round_levels(43.21)["below"] == 40.0
