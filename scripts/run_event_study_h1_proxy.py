"""M2.5 — Event study đợt 5: H1 cascade fade bằng PROXY (liquidationSnapshot không có trên
data.binance.vision — đã probe 404 toàn bộ; PLAN mục 12 đã sửa).

Pre-registered: H1_cascade_proxy_long — proxy cascade = ΔOI(1h) ≤ −2σ(1h) VÀ giá rơi ≥ 2% trong 1h
(forced selling flush) → drift LÊN sau flush (exhaustion fade).
Chỉ 1 giả thuyết duy nhất được đăng ký (slot 23/25).

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h1_proxy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.features.orderflow import add_oi_context, load_oi
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask

CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
SEGMENT = "TRAIN_2020-10_2023-06"


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    oi = load_oi()
    sol_oi = add_oi_context(sol[["close"]].copy(), oi)
    doi = sol_oi["oi_delta_1h"]
    doi_sigma = doi.rolling(288).std()  # σ 24h
    ret_1h = sol["close"].pct_change(12)

    # Cascade proxy: OI rơi mạnh (xả lực bán ép) + giá rơi sâu trong cùng 1h
    cascade = ((doi <= -2 * doi_sigma) & (ret_1h <= -0.02)).fillna(False)
    # Entry khi intensity CẠN: bar đầu giá NGỪNG lập đáy mới sau cascade (overshoot-and-revert)
    new_low = sol["close"] <= sol["close"].rolling(12).min()
    flush_end = cascade & ~new_low

    hl.register("H1_cascade_proxy_long", "H1 cascade exhaustion fade (proxy OI+price)",
                "M2.6 H1 (proxy — liquidationSnapshot không có)", CRITERIA, SEGMENT)
    train = split_mask(sol.index, "TRAIN")
    val = split_mask(sol.index, "VAL")

    print(f"cascade bars: {int(cascade.sum())}, flush_end: {int(flush_end.sum())}")
    res = events.run_event_study(sol, flush_end & train, "H1_cascade_proxy_long", sign=1)
    verdict = events.judge(res, "TRAIN", CRITERIA)
    extra = ""
    if verdict == "pass":
        res_val = events.run_event_study(sol, flush_end & val, "H1_cascade_proxy_long", sign=1)
        v = events.judge(res_val, "VAL", CRITERIA)
        extra = f" | VAL ex+1h={res_val.excess_by_horizon['+1h']:.4%} → {v}"
        if v == "keep_direction":
            verdict = "pass+VAL"
    hl.record_verdict("H1_cascade_proxy_long", "kill" if verdict == "kill" else "pass", {
        "train_excess": res.excess_by_horizon, "t_plus1h": res.t_by_horizon["+1h"],
        "n": res.n_events, "mfe_mae": res.mfe_mae_stats})
    ex = res.excess_by_horizon
    print(f"{'H1_cascade_proxy_long':<26}{res.n_events:>7}{ex['+15m']:>9.4%}{ex['+1h']:>9.4%}"
          f"{ex['+4h']:>9.4%}{res.t_by_horizon['+1h']:>7.2f}{verdict:>10}{extra}")


if __name__ == "__main__":
    main()
