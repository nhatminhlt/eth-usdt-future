"""M2.5 — Event study đợt 1: H3 seasonality cơ học (rẻ nhất trong menu M2.6).

Giả thuyết (đều pre-registered vào ledger trước khi chạy):
- H3a_hour_open_long/short : bar đầu giờ UTC → drift 4–12h (quarter-hour effect literature)
- H3b_quarter_open_long/short : bar đầu quarter-hour
- H3c_post_funding_long/short : bar NGAY SAU mốc funding (00/08/16 UTC)

Tiêu chí: excess ≥ 0.05% @+1h, t ≥ 2 trên TRAIN (CI bootstrap không chứa 0);
pass → VAL phải giữ hướng. Kill → ghi ledger, không backtest.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h3.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask

CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
SEGMENT = "TRAIN_2020-10_2023-06"


def main() -> None:
    df = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet")
    df = df.sort_index()
    train = split_mask(df.index, "TRAIN")
    val = split_mask(df.index, "VAL")

    minute = df.index.minute
    hour = df.index.hour
    events_def = {
        "H3a_hour_open": (minute == 0, "M2.6 H3 quarter-hour effect"),
        "H3b_quarter_open": (minute.isin([0, 15, 30, 45]), "M2.6 H3 turn-of-candle"),
        "H3c_post_funding": ((minute == 0) & (hour % 8 == 0), "M2.6 H3 funding-mark dynamics"),
    }
    print(f"{'hid':<28}{'n':>7}{'ex+15m':>9}{'ex+1h':>9}{'ex+4h':>9}{'t+1h':>7}{'verdict':>10}")
    for name, (mask, source) in events_def.items():
        for sign, tag in ((1, "long"), (-1, "short")):
            hid = f"{name}_{tag}"
            hl.register(hid, f"{name} drift {tag}", source, CRITERIA, SEGMENT)
            m_train = mask & train
            res = events.run_event_study(df, m_train, hid, sign=sign)
            verdict = events.judge(res, "TRAIN", CRITERIA)
            extra = ""
            if verdict == "pass":
                res_val = events.run_event_study(df, mask & val, hid, sign=sign)
                v = events.judge(res_val, "VAL", CRITERIA)
                extra = f" | VAL: ex+1h={res_val.excess_by_horizon['+1h']:.4%} → {v}"
                if v == "keep_direction":
                    verdict = "pass+VAL"
            hl.record_verdict(hid, "kill" if verdict == "kill" else "pass", {
                "train": {k: v for k, v in res.excess_by_horizon.items()},
                "t_plus1h": res.t_by_horizon["+1h"],
                "n": res.n_events,
                "mfe_mae": res.mfe_mae_stats,
            })
            print(f"{hid:<28}{res.n_events:>7}"
                  f"{res.excess_by_horizon['+15m']:>9.4%}"
                  f"{res.excess_by_horizon['+1h']:>9.4%}"
                  f"{res.excess_by_horizon['+4h']:>9.4%}"
                  f"{res.t_by_horizon['+1h']:>7.2f}{verdict:>10}{extra}")


if __name__ == "__main__":
    main()
