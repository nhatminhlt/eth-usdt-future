"""Cost model (PLAN M4 costs.py) — mọi phí theo giả định BNB (luật 7), 2 kịch bản song song,
không định trước kịch bản chính (vòng 8). Chi phí đo từ aggTrades thật (luật 6), không giả định:
spread/slippage/stop-multiplier đọc từ data/costs/cost_calibration_summary.json (calibrate_costs.py).

Kịch bản (settings.cost_scenarios):
- maker_base : entry post-only limit (maker) → TP limit maker → SL stop-market taker + slippage stop
- taker_worst: entry market taker + slippage  → TP limit maker → SL stop-market taker + slippage stop
Funding: rate THẬT từng kỳ (không giảm BNB), tính khi vị thế băng qua mốc settle.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from solfut.config import settings
from solfut.data.downloader import DATA_DIR

COST_DIR = DATA_DIR / "costs"

SCENARIOS = ("maker_base", "taker_worst")


@dataclass
class CostModel:
    maker_fee: float          # fraction, BNB -10%
    taker_fee: float          # fraction, BNB -10%
    taker_slippage: float     # fraction — market order điều kiện thường (half-spread + impact Q2)
    stop_slippage_mult: float  # đo từ aggTrades (V2: 1.03; V1 giả định 1.5)
    fee_scale: float = 1.0     # sensitivity ±50% → 1.5 (bao trùm hết-BNB +11%)

    # --- phí mỗi bên lệnh (fraction trên notional) theo loại fill ---
    def entry_cost(self, scenario: str) -> tuple[float, float]:
        """(fee, slippage) cho lệnh entry theo kịch bản."""
        if scenario == "maker_base":
            return self.maker_fee * self.fee_scale, 0.0
        return self.taker_fee * self.fee_scale, self.taker_slippage * self.fee_scale

    def tp_cost(self) -> tuple[float, float]:
        return self.maker_fee * self.fee_scale, 0.0   # TP limit maker

    def sl_cost(self) -> tuple[float, float]:
        # SL luôn kích hoạt lúc biến động mạnh → slippage × multiplier đo được
        return self.taker_fee * self.fee_scale, self.taker_slippage * self.fee_scale * self.stop_slippage_mult

    def market_exit_cost(self) -> tuple[float, float]:
        """Thoát theo thời gian / flat cuối ngày — market taker."""
        return self.taker_fee * self.fee_scale, self.taker_slippage * self.fee_scale


def load_cost_model(fee_scale: float = 1.0) -> CostModel:
    fees = settings()["fees"]
    summary_path = COST_DIR / "cost_calibration_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    spread_bps = summary["median_roll_spread_bps"]
    # market slippage ≈ half-spread + impact cỡ nhỏ (notional ~10² USDT → Q2)
    impact_q2_bps = summary["size_impact_5s_bps_abs"]["Q2"]
    taker_slippage = (spread_bps / 2 + impact_q2_bps) / 1e4
    return CostModel(
        maker_fee=fees["maker_pct"] / 100,
        taker_fee=fees["taker_pct"] / 100,
        taker_slippage=taker_slippage,
        stop_slippage_mult=summary["stop_slippage_multiplier_measured"],
        fee_scale=fee_scale,
    )


@dataclass
class FundingSchedule:
    """Rate funding THẬT theo mốc settle (luật 17 — không hardcode 8h; parquet lưu timestamp thực)."""
    rates: dict = field(default_factory=dict)   # {Timestamp(mốc, floor 5m): rate}

    def __post_init__(self) -> None:
        if self.rates:
            items = sorted((pd.Timestamp(k), v) for k, v in self.rates.items())
            self._marks = np.array([
                k.tz_convert("UTC").tz_localize(None).to_datetime64() if k.tzinfo is not None
                else k.to_datetime64() for k, _ in items])
            self._vals = np.array([v for _, v in items])
        else:
            self._marks, self._vals = None, None

    @classmethod
    def load(cls, symbol: str = "SOLUSDT") -> "FundingSchedule":
        import pandas as pd
        path = DATA_DIR / "funding" / f"{symbol}_funding.parquet"
        out = {}
        if path.exists():
            df = pd.read_parquet(path)
            ts = pd.to_datetime(df["fundingTime"], utc=True, unit="ms")
            out = {t.floor("5min"): float(r) for t, r in zip(ts, df["fundingRate"])}
        return cls(rates=out)

    def cost_between(self, entry_ts, exit_ts, notional: float, direction: int) -> float:
        """Chi phí funding cho vị thế giữ từ entry_ts đến exit_ts (exclusive-exit).
        rate > 0 → long TRẢ (funding_cost dương = mất tiền), short nhận; rate < 0 đảo lại."""
        if self._marks is None:
            return 0.0
        a = np.searchsorted(self._marks, np.datetime64(pd.Timestamp(entry_ts).tz_convert("UTC").tz_localize(None)), "right")
        b = np.searchsorted(self._marks, np.datetime64(pd.Timestamp(exit_ts).tz_convert("UTC").tz_localize(None)), "right")
        if b <= a:
            return 0.0
        return float(direction * self._vals[a:b].sum() * notional)
