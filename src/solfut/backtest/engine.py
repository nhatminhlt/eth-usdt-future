"""Backtest engine (PLAN M4 engine.py) — event-driven cho tín hiệu rời rạc (A/B/C), mỗi lần chạy
một lượt duy nhất trên toàn bộ signals (không loop Python theo tham số — luật 14: grid thì dùng
broadcast; engine này phục vụ đánh giá chiến thuật cố định + random baseline).

Ngữ nghĩa khớp lệnh (đúng PLAN M4):
- Taker entry: market tại CLOSE nến signal — thoát quét từ NẾN KẾ (chống lookahead).
- Maker entry: post-only limit tại extreme nến event (long = low). Fill rule TRADE-THROUGH:
  chỉ khớp khi giá ĐI XUYÊN QUA mức limit (long: low < limit), chạm đúng = không khớp
  (touch-fill của vectorbt lạc quan cho maker). Gap xuyên limit → khớp tại open.
  Order sống `patience_bars` nến; hết hạn = miss (đếm non-fill rate).
- Same-bar SL+TP: chạy 2 bound — `sl_first` (bi quan, báo cáo chính) và `tp_first` (lạc quan).
  Chỉ lãi ở bound tp_first → fragile, loại (luật 8).
- SL khớp stop-market gap-aware (long: open < SL → khớp tại open); TP khớp limit gap-aware.
- Thoát: SL / TP / time (holding_bars) / flat cuối ngày UTC (eod) — không giữ vị thế qua đêm.
- Funding rate THẬT áp khi vị thế băng qua mốc settle (chi phí signed theo direction).
- MỘT vị thế + một pending order tại một thời điểm (signal trong lúc bận bị bỏ, có đếm).
- Activity mask (phiên/tin/funding blackout) chặn entry tại nến bị cấm.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from solfut.backtest.account import size_position
from solfut.backtest.costs import CostModel, FundingSchedule


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series          # equity sau mỗi lệnh (index = exit_time)
    stats: dict


def run_backtest(
    ohlc: pd.DataFrame,
    signals: pd.DataFrame,
    cost: CostModel,
    scenario: str = "maker_base",
    bound: str = "sl_first",
    activity: np.ndarray | None = None,
    patience_bars: int = 12,
    funding: FundingSchedule | None = None,
    equity_start: float | None = None,
) -> BacktestResult:
    assert bound in ("sl_first", "tp_first"), "bound phải là sl_first | tp_first"
    assert scenario in ("maker_base", "taker_worst"), f"kịch bản lạ: {scenario}"
    from solfut.config import settings
    if equity_start is None:
        equity_start = settings()["risk"]["equity_start"]

    idx = ohlc.index
    n = len(idx)
    o = ohlc["open"].to_numpy(float)
    h = ohlc["high"].to_numpy(float)
    l = ohlc["low"].to_numpy(float)
    c = ohlc["close"].to_numpy(float)
    d = idx.floor("D").values                        # NGÀY UTC — so ngày, không so timestamp
    # nến cuối mỗi ngày UTC (flat trong ngày)
    last_of_day = np.empty(n, dtype=bool)
    last_of_day[:-1] = d[:-1] != d[1:]
    last_of_day[-1] = True

    sig = signals.sort_values("entry_time").reset_index(drop=True)
    sig_pos = idx.searchsorted(pd.DatetimeIndex(sig["entry_time"]))
    # nến cuối dataset có thời gian đóng chưa biết → không đặt lệnh mới ở đó
    valid = (sig_pos < n) & (idx[sig_pos.clip(max=n - 1)].values == pd.DatetimeIndex(sig["entry_time"]).values)

    trades: list[dict] = []
    equity = float(equity_start)
    busy_until = -1            # bar cuối mà vị thế/order đang chiếm chỗ (entry phải > busy_until)
    n_skip_position = n_skip_activity = n_skip_size = n_skip_eod = n_missed = 0

    for i in range(len(sig)):
        if not valid[i]:
            continue
        t = int(sig_pos[i])
        if t <= busy_until:
            n_skip_position += 1
            continue
        if activity is not None and not activity[t]:
            n_skip_activity += 1
            continue
        if last_of_day[t]:
            n_skip_eod += 1     # entry ở nến cuối ngày → buộc giữ qua đêm, cấm
            continue

        direction = int(sig.at[i, "direction"])
        anchor = float(sig.at[i, "entry_price"])
        sl_pct = float(sig.at[i, "sl_pct"])
        tp_pct = float(sig.at[i, "tp_pct"])
        holding = int(sig.at[i, "holding_bars"])
        sl_price = anchor * (1 - direction * sl_pct)
        tp_price = anchor * (1 + direction * tp_pct) if tp_pct == tp_pct else np.nan  # NaN = không TP (horizon exit)

        # --- ENTRY ---
        if scenario == "maker_base":
            limit = l[t] if direction > 0 else h[t]        # extreme nến event
            fill_t, fill_price = -1, np.nan
            for j in range(t + 1, min(t + 1 + patience_bars, n)):
                if direction > 0:
                    if o[j] < limit:
                        fill_price, fill_t = o[j], j       # gap xuyên limit → khớp tại open
                        break
                    if l[j] < limit:                       # trade-through, chạm đúng không khớp
                        fill_price, fill_t = limit, j
                        break
                else:
                    if o[j] > limit:
                        fill_price, fill_t = o[j], j
                        break
                    if h[j] > limit:
                        fill_price, fill_t = limit, j
                        break
            if fill_t < 0:
                n_missed += 1
                busy_until = min(t + patience_bars, n - 1)  # order chờ rồi hết hạn → vẫn chiếm chỗ
                continue
            entry_t, entry_price, entry_style = fill_t, fill_price, "post_only_limit"
        else:
            entry_t, entry_price, entry_style = t, c[t], "market_taker"

        dist_pct = direction * (entry_price - sl_price) / entry_price   # khoảng cách SL thực từ fill
        if dist_pct <= 0:
            n_skip_size += 1
            continue
        sizing = size_position(equity, dist_pct, entry_price)
        if sizing.rejected:
            n_skip_size += 1
            continue
        qty, notional, risk_usdt = sizing.qty, sizing.notional, sizing.risk_usdt

        fee_r, slip_r = cost.entry_cost(scenario)
        entry_fee, entry_slip = notional * fee_r, notional * slip_r

        # --- EXIT SCAN ---
        exit_t, exit_price, reason = -1, np.nan, ""
        j0 = entry_t if entry_style == "post_only_limit" else entry_t + 1
        for j in range(j0, n):
            sl_hit = l[j] <= sl_price if direction > 0 else h[j] >= sl_price
            tp_hit = (h[j] >= tp_price if direction > 0 else l[j] <= tp_price) \
                if tp_price == tp_price else False
            if sl_hit or tp_hit:
                if sl_hit and tp_hit:
                    hit_sl = bound == "sl_first"        # same-bar: bound quyết định
                else:
                    hit_sl = sl_hit
                if hit_sl:
                    exit_price = min(o[j], sl_price) if direction > 0 else max(o[j], sl_price)
                    reason = "sl"
                else:
                    exit_price = max(o[j], tp_price) if direction > 0 else min(o[j], tp_price)
                    reason = "tp"
                exit_t = j
                break
            if j - entry_t >= holding:
                exit_price, reason, exit_t = c[j], "time", j
                break
            if last_of_day[j]:
                exit_price, reason, exit_t = c[j], "eod", j
                break
        if exit_t < 0:                                      # hết dữ liệu chưa thoát
            exit_price, reason, exit_t = c[n - 1], "eod", n - 1

        if reason == "sl":
            fee_r, slip_r = cost.sl_cost()
        elif reason == "tp":
            fee_r, slip_r = cost.tp_cost()
        else:
            fee_r, slip_r = cost.market_exit_cost()
        exit_notional = qty * exit_price
        exit_fee, exit_slip = exit_notional * fee_r, exit_notional * slip_r

        funding_cost = 0.0
        if funding is not None:
            funding_cost = funding.cost_between(idx[entry_t], idx[exit_t], notional, direction)

        gross = direction * qty * (exit_price - entry_price)
        cost_total = entry_fee + entry_slip + exit_fee + exit_slip + funding_cost
        net = gross - cost_total
        equity += net
        busy_until = exit_t

        trades.append({
            "sid": sig.at[i, "sid"], "scenario": scenario, "bound": bound,
            "signal_time": idx[t], "entry_time": idx[entry_t], "exit_time": idx[exit_t],
            "direction": direction, "entry_style": entry_style,
            "entry_price": entry_price, "exit_price": exit_price,
            "sl_price": sl_price, "tp_price": tp_price,
            "qty": qty, "notional": notional, "risk_usdt": risk_usdt,
            "bars_held": exit_t - entry_t, "exit_reason": reason,
            "gross_pnl": gross, "entry_fee": entry_fee, "exit_fee": exit_fee,
            "slippage": entry_slip + exit_slip, "funding_cost": funding_cost,
            "cost_total": cost_total, "net_pnl": net,
            "r_gross": gross / risk_usdt, "r_net": net / risk_usdt,
        })

    tr = pd.DataFrame(trades)
    if len(tr):
        eq = equity_start + tr["net_pnl"].cumsum()
        eq.index = tr["exit_time"]
    else:
        eq = pd.Series(dtype=float)
    if scenario == "maker_base":
        denom = len(tr) + n_missed
        fill_rate = len(tr) / denom if denom else None
    else:
        fill_rate = None
    stats = {
        "n_signals": int(valid.sum()), "n_trades": len(tr),
        "fill_rate_maker": fill_rate, "n_missed_maker": n_missed,
        "n_skip_position": n_skip_position, "n_skip_activity": n_skip_activity,
        "n_skip_size": n_skip_size, "n_skip_eod_entry": n_skip_eod,
        "equity_end": equity,
    }
    return BacktestResult(trades=tr, equity=eq, stats=stats)
