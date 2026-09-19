"""Account sizing (PLAN M4 account.py) — Percent-Risk (Tharp): qty = risk / SL_distance,
làm tròn XUỐNG 0.01 SOL; check minNotional ≥ 5 USDT, qty ≥ 0.01, đòn bẩy hiệu dụng ≤ 5× isolated.
SL luôn trước thanh lý: 5× isolated → liquidation ≈ −19% ≫ SL tối đa (−1.2%).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solfut.config import settings


def floor_lot(qty_raw: float, lot: float) -> float:
    """Floor về lot step với epsilon chống lỗi float (2.5/0.01 = 249.999…)."""
    return math.floor(qty_raw / lot + 1e-9) * lot


@dataclass
class SizingResult:
    qty: float
    notional: float
    leverage: float
    risk_usdt: float
    rejected: str | None = None    # None = hợp lệ


def _contract(contract: dict | None) -> dict:
    if contract is not None:
        return contract
    c = dict(settings()["contract"])
    return {"lot_step": c["lot_step"], "min_qty": c["min_qty"],
            "min_notional": c["min_notional"], "leverage_cap": c["leverage_cap"]}


def size_position(equity: float, sl_distance_pct: float, price: float,
                  contract: dict | None = None) -> SizingResult:
    """Sizing cho 1 lệnh. sl_distance_pct: khoảng cách SL theo % giá (fraction dương).
    Risk cố định = equity × risk_per_trade_pct — lỗ tối đa khi SL khớp đúng mức."""
    c = _contract(contract)
    risk_pct = settings()["risk"]["risk_per_trade_pct"] / 100
    lot, min_qty = c["lot_step"], c["min_qty"]
    min_notional, lev_cap = c["min_notional"], c["leverage_cap"]

    dist = sl_distance_pct * price
    if not (dist > 0) or price <= 0:
        return SizingResult(0, 0, 0, 0, rejected="invalid_sl_distance")
    risk_usdt = equity * risk_pct
    qty = floor_lot(risk_usdt / dist, lot)
    if qty < min_qty:
        return SizingResult(0, 0, 0, risk_usdt, rejected="qty_below_min")
    notional = qty * price
    # đòn bẩy hiệu dụng = notional / equity — cap 5×: siết qty, kiểm tra lại minNotional
    max_qty = floor_lot(equity * lev_cap / price, lot)
    if qty > max_qty:
        qty = max_qty
        notional = qty * price
        if qty < min_qty:
            return SizingResult(0, 0, 0, risk_usdt, rejected="leverage_cap_min_conflict")
    if notional < min_notional:
        return SizingResult(0, 0, 0, risk_usdt, rejected="notional_below_min")
    return SizingResult(qty=qty, notional=notional, leverage=notional / equity,
                        risk_usdt=risk_usdt)


def size_position_governed(equity: float, sl_distance_pct: float, price: float,
                           risk_cap_pct: float = 2.0, lev_cap_eff: float = 1.0,
                           contract: dict | None = None) -> SizingResult:
    """Governed sizing cho lớp horizon/wide-stop (M4c evidence: percent-risk với SL ~9% →
    notional 5.3 USDT chạm sàn minNotional + R-dilution 10×).

    notional = max(min_notional, min(equity × lev_cap_eff, equity × risk_cap_pct/sl_pct))
    - risk_cap_pct: worst-case mất tối đa khi SL thiên tai khớp (% equity)
    - minNotional floor: sàn giao dịch từ chối lệnh nhỏ hơn (ETH = 20 USDT!) — nếu floor
      làm worst-case vượt risk_cap → REJECT (guard, không phá luật rủi ro)
    risk_usdt ghi nhận worst-case = notional × sl_distance_pct.
    """
    c = _contract(contract)
    lot, min_qty = c["lot_step"], c["min_qty"]
    min_notional, lev_cap = c["min_notional"], c["leverage_cap"]
    assert lev_cap_eff <= lev_cap, f"lev_cap_eff {lev_cap_eff} > cap hợp đồng {lev_cap}"

    dist = sl_distance_pct * price
    if not (dist > 0) or price <= 0:
        return SizingResult(0, 0, 0, 0, rejected="invalid_sl_distance")
    notional_target = max(min_notional,
                          min(equity * lev_cap_eff, equity * risk_cap_pct / 100 / sl_distance_pct))
    qty = floor_lot(notional_target / price, lot)
    if qty < min_qty:
        return SizingResult(0, 0, 0, 0, rejected="qty_below_min")
    notional = qty * price
    if notional < min_notional:
        return SizingResult(0, 0, 0, 0, rejected="notional_below_min")
    risk_usdt = notional * sl_distance_pct          # worst-case (SL thiên tai)
    if risk_usdt > equity * risk_cap_pct / 100:
        return SizingResult(0, 0, 0, 0, rejected="risk_cap_violated_by_min_notional")
    return SizingResult(qty=qty, notional=notional, leverage=notional / equity,
                        risk_usdt=risk_usdt)
