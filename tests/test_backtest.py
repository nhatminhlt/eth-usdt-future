"""Test M4 backtest layer: fill rules, same-bar bound, cost model, sizing, flat-trong-ngày,
funding, chống lookahead (entry close t → thoát từ t+1), random baseline.
Toàn bộ trên dữ liệu synthetic — deterministic, không phụ thuộc mạng/dữ liệu tải.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from solfut.backtest.costs import CostModel, FundingSchedule
from solfut.backtest.engine import run_backtest
from solfut.backtest.account import size_position, size_position_governed
from solfut.backtest.metrics import compute_metrics, gates_check
from solfut.backtest.monte_carlo import mc_drawdown, cost_shock_expectancy
from solfut.backtest.random_baseline import random_baseline, edge_vs_random


@pytest.fixture
def cost() -> CostModel:
    return CostModel(maker_fee=0.00018, taker_fee=0.00045,
                     taker_slippage=0.0001, stop_slippage_mult=1.0)


def make_ohlc(rows: list[tuple[float, float, float, float]], start="2024-01-01") -> pd.DataFrame:
    """rows: (open, high, low, close) — nến 5m liên tục từ start (UTC)."""
    idx = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return df


def make_signals(ohlc: pd.DataFrame, bars: list[int], direction=1, sl_pct=0.01,
                 tp_pct=0.02, holding=48, sid="T") -> pd.DataFrame:
    return pd.DataFrame({
        "entry_time": ohlc.index[bars], "sid": sid, "direction": direction,
        "entry_price": ohlc["close"].to_numpy(float)[bars],
        "sl_pct": sl_pct, "tp_pct": tp_pct, "holding_bars": holding,
    })


# ---------------------------------------------------------------- sizing
def test_sizing_lot_rounding_and_leverage():
    r = size_position(50.0, 0.007, 100.0)      # risk 0.5 USDT, SL 0.7 USDT → 0.71 SOL
    assert r.qty == pytest.approx(0.71)
    assert r.leverage < 5
    # SL cực mỏng → qty phình → bị cap 5× đòn bẩy
    r2 = size_position(50.0, 0.0001, 100.0)    # 0.005 USDT khoảng cách → cần 100 SOL
    assert r2.leverage <= 5 + 1e-9
    assert r2.qty == pytest.approx(2.5)
    # qty đủ min nhưng notional < 5 USDT → reject (SL 50%, price 100 → qty 0.01 = 1 USDT)
    r3 = size_position(50.0, 0.5, 100.0)
    assert r3.rejected == "notional_below_min"


def test_sizing_governed():
    """Governed sizing: notional = min(equity×lev, equity×risk_cap/sl) — lớp wide-stop."""
    # SL 9.47%: percent-risk cho notional 5.28 (chạm sàn); governed → target 10.56, lot-round 0.10 SOL = 10 USDT
    r = size_position_governed(50.0, 0.0947, 100.0, risk_cap_pct=2.0, lev_cap_eff=1.0)
    assert r.notional == pytest.approx(10.0)
    assert r.risk_usdt == pytest.approx(r.notional * 0.0947)   # worst-case
    assert r.risk_usdt <= 50.0 * 0.02 + 1e-9
    assert r.leverage <= 1.0 + 1e-9
    # SL mỏng → risk-cap binding, notional ≤ 1× equity
    r2 = size_position_governed(50.0, 0.01, 100.0, risk_cap_pct=2.0, lev_cap_eff=1.0)
    assert r2.notional == pytest.approx(50.0)                   # min(50, 1/0.01=100) → 50
    assert r2.leverage == pytest.approx(1.0)
    # lev_cap_eff > cap hợp đồng → lỗi
    with pytest.raises(AssertionError):
        size_position_governed(50.0, 0.05, 100.0, lev_cap_eff=7.0)


# ---------------------------------------------------------------- taker path
def test_taker_entry_close_and_exit_next_bar(cost):
    """Entry tại close nến signal; SL KHÔNG được khớp trên chính nến entry (chống lookahead)."""
    # close 100, SL 99 (1%) — nến entry có low 98.5 nhưng entry là market tại close
    ohlc = make_ohlc([
        (100, 100.5, 99.5, 100),
        (100, 100.5, 98.5, 99),        # nến sau: low chạm SL → thoát tại 99 (SL = 100×0.99)
        (99, 99, 98, 98.5),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=10)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first")
    assert len(res.trades) == 1
    tr = res.trades.iloc[0]
    assert tr["entry_style"] == "market_taker"
    assert tr["entry_time"] == ohlc.index[0]
    assert tr["exit_reason"] == "sl"
    assert tr["exit_time"] == ohlc.index[1]          # thoát ở nến KẾ, không phải nến entry
    assert tr["exit_price"] == pytest.approx(99.0)


def test_same_bar_sl_tp_bound(cost):
    """Một nến quét cả SL lẫn TP: bound sl_first → thoát SL; tp_first → thoát TP (luật 8)."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 103, 98, 100),           # nến sau quét cả 99 (SL) và 102 (TP)
        (100, 100, 100, 100),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=10)
    r_sl = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first")
    r_tp = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="tp_first")
    assert r_sl.trades.iloc[0]["exit_reason"] == "sl"
    assert r_tp.trades.iloc[0]["exit_reason"] == "tp"


def test_gap_through_sl_fills_at_open(cost):
    """Gap xuống dưới SL → stop-market khớp tại OPEN (tệ hơn SL), không phải giá SL."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (97, 98, 96, 97),              # open 97 < SL 99 → khớp 97
        (97, 97, 96, 96.5),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=10)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst")
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "sl"
    assert tr["exit_price"] == pytest.approx(97.0)


def test_time_exit_and_eod_flat(cost):
    """Holding hết → thoát close; vị thế KHÔNG bao giờ trôi qua nửa đêm UTC."""
    # 2 ngày, mỗi ngày 288 nến 5m; entry bar 200 ngày 1, holding 600 (sẽ vượt nửa đêm)
    d1 = [(100, 100.1, 99.9, 100)] * 288
    d2 = [(100, 100.1, 99.9, 100)] * 288
    ohlc = make_ohlc(d1 + d2)
    sig = make_signals(ohlc, [200], sl_pct=0.01, tp_pct=0.02, holding=600)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst")
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "eod"
    assert tr["exit_time"].date() == ohlc.index[200].date()   # đóng trong cùng ngày UTC
    # entry ở nến cuối ngày bị chặn
    sig2 = make_signals(ohlc, [287], sl_pct=0.01, tp_pct=0.02, holding=10)
    res2 = run_backtest(ohlc, sig2, cost, scenario="taker_worst")
    assert len(res2.trades) == 0 and res2.stats["n_skip_eod_entry"] == 1


# ---------------------------------------------------------------- maker path
def test_maker_trade_through_fill_rule(cost):
    """Touch đúng mức limit KHÔNG khớp; đi xuyên qua mới khớp tại limit; gap → khớp tại open."""
    # limit = low nến event = 99.0
    base = [(100, 100, 99, 100)]                     # event bar: low 99 → limit 99
    touch = [(100, 100, 99.0, 100)]                  # chạm đúng 99.0 → KHÔNG khớp
    through = [(100, 100, 98.9, 100)]                # xuyên 98.9 → khớp 99.0
    gap = [(98.5, 99, 98, 99)]                       # open 98.5 < 99 → khớp 98.5
    tail = [(100, 100, 100, 100)] * 20

    sig_touch = make_signals(make_ohlc(base + touch + tail), [0], sl_pct=0.02, tp_pct=0.02)
    res_t = run_backtest(make_ohlc(base + touch + tail), sig_touch, cost, scenario="maker_base")
    assert len(res_t.trades) == 0 and res_t.stats["n_missed_maker"] == 1

    ohlc_th = make_ohlc(base + through + tail)
    sig_th = make_signals(ohlc_th, [0], sl_pct=0.02, tp_pct=0.02)
    res_th = run_backtest(ohlc_th, sig_th, cost, scenario="maker_base")
    assert len(res_th.trades) == 1
    assert res_th.trades.iloc[0]["entry_price"] == pytest.approx(99.0)
    assert res_th.trades.iloc[0]["entry_style"] == "post_only_limit"

    ohlc_gap = make_ohlc(base + gap + tail)
    sig_gap = make_signals(ohlc_gap, [0], sl_pct=0.02, tp_pct=0.02)
    res_gap = run_backtest(ohlc_gap, sig_gap, cost, scenario="maker_base")
    assert res_gap.trades.iloc[0]["entry_price"] == pytest.approx(98.5)


def test_maker_patience_expiry(cost):
    """Limit không được chạm lại trong patience → miss, và slot bị chiếm trong patience."""
    base = [(100, 100, 99, 100)]
    away = [(100, 100.2, 100, 100.1)] * 15           # không bao giờ quay lại 99
    ohlc = make_ohlc(base + away)
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02)
    res = run_backtest(ohlc, sig, cost, scenario="maker_base", patience_bars=12)
    assert len(res.trades) == 0 and res.stats["n_missed_maker"] == 1
    # signal thứ 2 trong lúc order pending → bị skip vì bận
    sig2 = make_signals(ohlc, [0, 5], sl_pct=0.01, tp_pct=0.02)
    res2 = run_backtest(ohlc, sig2, cost, scenario="maker_base", patience_bars=12)
    assert res2.stats["n_skip_position"] == 1


# ---------------------------------------------------------------- maker exit
def test_maker_exit_fills_on_trade_through(cost):
    """Time-exit qua limit maker: giá đi XUYÊN qua close thoát → khớp tại limit, phí maker."""
    # entry bar 0, holding 2 → quyết định thoát tại close bar 2 = 100; bar 3 xuyên lên 101
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 100, 99.5, 100),
        (100, 100, 100, 100),          # close 100 = mức limit thoát
        (100, 101, 99.8, 100.8),       # high 101 > 100 → khớp tại 100 (trade-through)
        (100, 100, 100, 100),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.05, tp_pct=0.20, holding=2)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first",
                       exit_maker=True, exit_patience=3)
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "time_maker"
    assert tr["exit_time"] == ohlc.index[3]
    assert tr["exit_fee"] == pytest.approx(tr["qty"] * tr["exit_price"] * cost.maker_fee)
    assert tr["slippage"] == pytest.approx(tr["qty"] * tr["entry_price"] * cost.taker_slippage)


def test_maker_exit_fallback_when_no_fill(cost):
    """Giá không quay lại → hết patience → fallback market taker."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 100, 99.5, 99.6),
        (100, 100, 100, 99.0),         # close thoát 99.0
        (98.5, 98.6, 98, 98.2),        # rơi tiếp — không fill (high < 99)
        (98.0, 98.2, 97.8, 98.0),
        (98.0, 98.0, 97.5, 97.6),      # bar patience cuối (j+3) → fallback tại close 97.6
        (97.6, 97.8, 97.4, 97.6),      # nến thêm để bar trên không phải cuối dataset
        (97.6, 97.8, 97.4, 97.6),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.05, tp_pct=0.20, holding=2)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first",
                       exit_maker=True, exit_patience=3)
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "time_fallback"
    assert tr["exit_price"] == pytest.approx(97.6)
    assert res.stats["maker_exit_fill_rate"] == 0.0


def test_maker_exit_gap_up_fills_at_open(cost):
    """Gap lên trên limit → khớp tại open (giá tốt hơn cho người bán)."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 100, 99.5, 100),
        (100, 100, 100, 100),          # limit thoát = 100
        (101.5, 102, 101, 101.5),      # open 101.5 > 100 → khớp 101.5
        (100, 100, 100, 100),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.05, tp_pct=0.20, holding=2)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first",
                       exit_maker=True, exit_patience=3)
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "time_maker"
    assert tr["exit_price"] == pytest.approx(101.5)


def test_maker_exit_sl_priority_during_wait(cost):
    """SL vẫn sống trong lúc chờ fill: giá sập xuyên SL → thoát stop-market ưu tiên."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 100, 99.5, 100),
        (100, 100, 100, 100),          # limit thoát = 100
        (99.0, 99.2, 98.0, 98.5),      # low 98 < SL 95? — SL = 100×0.95 = 95; chưa xuyên
        (95.5, 95.8, 94.0, 94.5),      # low 94 < 95 → SL khớp tại 95
        (94, 94, 93, 93.5),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.05, tp_pct=0.20, holding=2)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", bound="sl_first",
                       exit_maker=True, exit_patience=3)
    tr = res.trades.iloc[0]
    assert tr["exit_reason"] == "sl"
    assert tr["exit_price"] == pytest.approx(95.0)


# ---------------------------------------------------------------- costs & funding
def test_cost_math_exact(cost):
    """Phí/slippage từng bên tính đúng theo kịch bản taker_worst."""
    ohlc = make_ohlc([
        (100, 100, 100, 100),
        (100, 102.1, 99.5, 100),        # TP 102 hit, không chạm SL 99 → thoát limit maker
        (100, 100, 100, 100),
    ])
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=10)
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst")
    tr = res.trades.iloc[0]
    qty, ep, xp = tr["qty"], tr["entry_price"], tr["exit_price"]
    assert tr["entry_fee"] == pytest.approx(qty * ep * cost.taker_fee)
    assert tr["slippage"] == pytest.approx(qty * ep * cost.taker_slippage
                                           + qty * xp * 0.0)   # TP maker không slippage
    assert tr["exit_fee"] == pytest.approx(qty * xp * cost.maker_fee)
    assert tr["funding_cost"] == 0.0


def test_funding_applied_when_crossing_mark():
    """Vị thế băng qua mốc funding → trả rate × notional (long trả khi rate dương)."""
    cost = CostModel(0.00018, 0.00045, 0.0001, 1.0)
    fs = FundingSchedule(rates={pd.Timestamp("2024-01-01 16:00", tz="UTC"): 0.0001})
    d1 = [(100, 100.1, 99.9, 100)] * 200              # 00:00→16:35
    ohlc = make_ohlc(d1)
    sig = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=195)   # thoát 16:15, giữ qua 16:00
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", funding=fs)
    tr = res.trades.iloc[0]
    assert tr["funding_cost"] == pytest.approx(tr["notional"] * 0.0001)   # long TRẢ rate dương
    # funding dương = CHI PHÍ cho long → net giảm
    sig2 = make_signals(ohlc, [0], sl_pct=0.01, tp_pct=0.02, holding=195)
    res2 = run_backtest(ohlc, sig2, cost, scenario="taker_worst", funding=None)
    assert res.trades.iloc[0]["net_pnl"] < res2.trades.iloc[0]["net_pnl"]


def test_activity_mask_blocks_entry(cost):
    ohlc = make_ohlc([(100, 100, 100, 100)] * 10)
    sig = make_signals(ohlc, [3], sl_pct=0.01, tp_pct=0.02)
    act = np.ones(10, dtype=bool)
    act[3] = False
    res = run_backtest(ohlc, sig, cost, scenario="taker_worst", activity=act)
    assert len(res.trades) == 0 and res.stats["n_skip_activity"] == 1


# ---------------------------------------------------------------- metrics & gates
def test_metrics_and_gates_synthetic(cost):
    rng = np.random.default_rng(0)
    n = 300
    r_net = rng.normal(0.08, 1.0, n)
    tr = pd.DataFrame({
        "entry_time": pd.date_range("2024-01-01", periods=n, freq="6h", tz="UTC"),
        "exit_time": pd.date_range("2024-01-01 01:00", periods=n, freq="6h", tz="UTC"),
        "r_net": r_net, "r_gross": r_net + 0.003,
        "net_pnl": r_net * 0.5, "gross_pnl": (r_net + 0.003) * 0.5,
        "cost_total": np.full(n, 0.003 * 0.5), "risk_usdt": np.full(n, 0.5),
        "bars_held": np.full(n, 12), "exit_reason": "time",
    })
    m = compute_metrics(tr)
    assert m["n_trades"] == 300
    assert m["expectancy_r"] == pytest.approx(r_net.mean(), abs=1e-9)
    lo, hi = m["expectancy_ci95"]
    assert lo < r_net.mean() < hi
    g = gates_check(m)
    assert g["n_trades"]["ok"] and g["ci_excludes_zero"]["ok"] is (lo > 0)
    assert "ALL_PASS" in g


def test_mc_and_cost_shock():
    rng = np.random.default_rng(1)
    r = rng.normal(0.05, 1.0, 400)
    mc = mc_drawdown(r, n_sims=200)
    assert 0 < mc["max_dd_p50"] < mc["max_dd_p99"]
    cs = cost_shock_expectancy(np.full(400, 0.02), expectancy_r=0.05, scale=1.5)
    assert cs["expectancy_r_shocked"] == pytest.approx(0.05 - 0.01)


def test_random_baseline_runs(cost):
    ohlc = make_ohlc([(100, 100.5, 99.5, 100)] * 2000)
    base = random_baseline(ohlc, n_trades_target=50, cost=cost, scenario="taker_worst",
                           bound="sl_first", sl_pct=0.01, tp_pct=0.02, holding_bars=12,
                           k_seeds=5, seed=1)
    assert "error" not in base
    assert base["k_seeds"] == 5
    e = edge_vs_random(strategy_expectancy_r=0.1, baseline=base)
    assert "edge_r" in e and "beats_random_p95" in e
