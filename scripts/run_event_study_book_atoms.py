"""M2.5 — Event study đợt 4: trigger atom của 3 chiến thuật sách (S1 Volman / S2 Brooks / S3 Carter).

Luật 12: không có backtest nào chạy trước khi giả thuyết trigger của nó pass event-study.
Đây là "bài kiểm tra hộ chiếu" cho S1/S2/S3 — pass mới được vào M3/M4.

- S1_box_at_barrier_long  : inside bar đóng trong 0.15% dưới round number (box đè barrier) → break-up drift
- S1_box_at_barrier_short : inside bar đóng trong 0.15% trên round number → break-down drift
- S2_h2l2_pullback_long   : reversal_bull + 3 bar gần nhất chạm EMA20 + always_in_long → drift lên
- S2_l2_pullback_short    : mirror short
- S3_squeeze_release_long : squeeze ON ≥ 12 bar rồi powerbar_bull → drift lên
- S3_squeeze_release_short: squeeze ON ≥ 12 bar rồi powerbar_bear → drift xuống

Chạy: .venv/Scripts/python.exe scripts/run_event_study_book_atoms.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask

CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
SEGMENT = "TRAIN_2020-10_2023-06"


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    price = sol["close"]

    # S1: inside bar đè sát round number (khoảng cách tới round level ≤ 0.15% giá)
    near_below_round = (sol["round_above"] - price) <= 0.0015 * price
    near_above_round = (price - sol["round_below"]) <= 0.0015 * price
    s1_long = (sol["inside_bar"] & near_below_round).fillna(False)
    s1_short = (sol["inside_bar"] & near_above_round).fillna(False)

    # S2: H2/L2 pullback — reversal bar + pullback chạm EMA20 (3 bar gần nhất) + always-in cùng hướng
    touched_ema20 = (sol["low"] <= sol["ema20"]).rolling(3).max().astype(bool)
    touched_ema20_up = (sol["high"] >= sol["ema20"]).rolling(3).max().astype(bool)
    s2_long = (sol["reversal_bull"] & touched_ema20 & sol["always_in_long"]).fillna(False)
    s2_short = (sol["reversal_bear"] & touched_ema20_up & sol["always_in_short"]).fillna(False)

    # S3: squeeze release — BB nằm trong KC ≥ 12 bar rồi powerbar cùng hướng
    squeeze_on = ((sol["bb_up"] < sol["kc_up"]) & (sol["bb_low"] > sol["kc_low"])).fillna(False)
    squeeze_len = squeeze_on.rolling(12).sum()
    squeeze_ready = squeeze_len >= 12
    s3_long = (squeeze_ready & sol["powerbar_bull"]).fillna(False)
    s3_short = (squeeze_ready & sol["powerbar_bear"]).fillna(False)

    train = split_mask(sol.index, "TRAIN")
    val = split_mask(sol.index, "VAL")

    cases = [
        ("S1_box_at_barrier_long", s1_long, 1),
        ("S1_box_at_barrier_short", s1_short, -1),
        ("S2_h2l2_pullback_long", s2_long, 1),
        ("S2_l2_pullback_short", s2_short, -1),
        ("S3_squeeze_release_long", s3_long, 1),
        ("S3_squeeze_release_short", s3_short, -1),
    ]
    print(f"{'hid':<30}{'n':>7}{'ex+15m':>9}{'ex+1h':>9}{'ex+4h':>9}{'t+1h':>7}{'verdict':>10}")
    for name, mask, sign in cases:
        hl.register(name, name, f"M2.6 book atom ({'long' if sign == 1 else 'short'})",
                    CRITERIA, SEGMENT)
        res = events.run_event_study(sol, mask & train, name, sign=sign)
        verdict = events.judge(res, "TRAIN", CRITERIA)
        extra = ""
        if verdict == "pass":
            res_val = events.run_event_study(sol, mask & val, name, sign=sign)
            v = events.judge(res_val, "VAL", CRITERIA)
            extra = f" | VAL ex+1h={res_val.excess_by_horizon['+1h']:.4%} → {v}"
            if v == "keep_direction":
                verdict = "pass+VAL"
        hl.record_verdict(name, "kill" if verdict == "kill" else "pass", {
            "train_excess": res.excess_by_horizon, "t_plus1h": res.t_by_horizon["+1h"],
            "n": res.n_events, "mfe_mae": res.mfe_mae_stats})
        ex = res.excess_by_horizon
        print(f"{name:<30}{res.n_events:>7}{ex['+15m']:>9.4%}{ex['+1h']:>9.4%}"
              f"{ex['+4h']:>9.4%}{res.t_by_horizon['+1h']:>7.2f}{verdict:>10}{extra}")


if __name__ == "__main__":
    main()
