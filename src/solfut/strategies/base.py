"""Khung chiến thuật chung (M3).

Luật áp dụng: chỉ chiến thuật có giả thuyết pass event-study mới được sinh tín hiệu (luật 12/16);
S1/S2/S3 sách đã KILL ở event-study → không backtest. Percent-Risk sizing, SL/TP derive từ
phân phối MFE/MAE của giả thuyết (ledger), flat trong ngày, conflict resolver.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class StrategySpec:
    sid: str
    hypothesis_id: str          # phải là hid PASS trong ledger
    direction: int              # +1 long, −1 short
    holding_bars: int           # kỳ vọng từ decay curve của giả thuyết
    sl_from_mae_q: float = 0.25  # SL = |MAE q25| của event distribution
    tp_from_mfe_q: float = 0.75  # TP = MFE q75
    entry_style: str = "stop_market"  # "stop_market" (taker) | "post_only_limit" (maker)


def load_passing_hypotheses() -> dict[str, dict]:
    from solfut.research.hypotheses import load_all
    return {r["hid"]: r for r in load_all() if r["verdict"] == "pass"}


def derive_sl_tp(spec: StrategySpec, ledger_row: dict) -> dict:
    """SL/TP từ MFE/MAE của event study (PLAN M2.5: derive, không grid mù)."""
    mm = ledger_row["result"].get("mfe_mae", {})
    mae_q = abs(mm.get("mae_q25", float("nan")))
    mfe_q = mm.get("mfe_q75", float("nan"))
    if not (mae_q > 0) or not (mfe_q > 0):
        raise ValueError(f"{spec.sid}: MFE/MAE không hợp lệ trong ledger — chạy lại event study")
    return {"sl_pct": mae_q, "tp_pct": mfe_q, "rr": mfe_q / mae_q}


def conflict_resolver(signals: pd.DataFrame) -> pd.DataFrame:
    """Cùng nến nhiều tín hiệu: cùng hướng giữ 1 (ưu tiên expectancy cao — ở đây rank theo
    t-stat giả thuyết, tĩnh vì expectancy chưa có), ngược hướng skip cả hai (luật 11)."""
    if signals.empty:
        return signals
    keep_rows = []
    for ts, grp in signals.groupby("entry_time"):
        dirs = grp["direction"].unique()
        if len(dirs) > 1:
            continue  # ngược hướng → skip cả hai
        keep_rows.append(grp.sort_values("hypothesis_t", ascending=False).iloc[0])
    return pd.DataFrame(keep_rows) if keep_rows else signals.iloc[0:0]
