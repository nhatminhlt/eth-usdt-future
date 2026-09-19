"""M2.5 — Event study đợt 2: H2 BTC→SOL lead-lag + H4 order-flow + OI quadrant.

Pre-registered trước khi chạy (ledger). Dữ liệu: SOL enriched, BTC 5m, metrics OI (từ 2021-12).

- H2a_btc_jump_up_continuation_long  : BTC 5m bar đóng với return ≥ +2σ → SOL drift tiếp diễn?
- H2b_btc_jump_down_seesaw_long      : BTC return ≤ −2σ → SOL seesaw (drift lên)? (Jia 2023)
- H4a_taker_surge_long/short         : taker imbalance fast z-score ≥ +2 (≤ −2) → drift?
- H4b_oi_fresh_long                  : quadrant oi_up_price_up (tiền mới vào cùng hướng) → drift?
- H4c_oi_squeeze_long                : quadrant oi_down_price_up (short squeeze) → drift?

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h2h4.py
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
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    btc_ret = btc["close"].pct_change()
    btc_sigma = btc_ret.rolling(96).std()  # σ 8h trên BTC 5m
    btc_jump_up = (btc_ret >= 2 * btc_sigma).reindex(sol.index).fillna(False)
    btc_jump_dn = (btc_ret <= -2 * btc_sigma).reindex(sol.index).fillna(False)

    imb_z = ((sol["taker_imbalance_fast"] - sol["taker_imbalance_fast"].rolling(288).mean())
             / sol["taker_imbalance_fast"].rolling(288).std())
    imb_up = (imb_z >= 2).fillna(False)
    imb_dn = (imb_z <= -2).fillna(False)

    # OI quadrant — recompute trên toàn dải có metrics (orderflow.add_oi_context cần OI)
    from solfut.features.orderflow import add_oi_context, load_oi
    oi = load_oi()
    sol_oi = add_oi_context(sol[["close"]].copy(), oi)
    q_fresh = (sol_oi["oi_quadrant"] == "oi_up_price_up")
    q_squeeze = (sol_oi["oi_quadrant"] == "oi_down_price_up")

    train = split_mask(sol.index, "TRAIN")
    val = split_mask(sol.index, "VAL")

    cases = [
        ("H2a_btc_jump_up_cont_long", btc_jump_up, 1, "M2.6 H2 lead-lag"),
        ("H2b_btc_jump_down_seesaw_long", btc_jump_dn, 1, "M2.6 H2 seesaw Jia 2023"),
        ("H4a_taker_surge_long", imb_up, 1, "M2.6 H4 OFI"),
        ("H4a_taker_surge_short", imb_dn, -1, "M2.6 H4 OFI"),
        ("H4b_oi_fresh_money_long", q_fresh, 1, "M2.6 H4 OI quadrant"),
        ("H4c_oi_squeeze_long", q_squeeze, 1, "M2.6 H4 OI quadrant"),
    ]
    print(f"{'hid':<32}{'n':>7}{'ex+15m':>9}{'ex+1h':>9}{'ex+4h':>9}{'t+1h':>7}{'verdict':>10}")
    for name, mask, sign, source in cases:
        hid = name if sign == 1 else name
        hl.register(hid, name, source, CRITERIA, SEGMENT)
        m_train = mask & train
        res = events.run_event_study(sol, m_train, hid, sign=sign)
        verdict = events.judge(res, "TRAIN", CRITERIA)
        extra = ""
        if verdict == "pass":
            res_val = events.run_event_study(sol, mask & val, hid, sign=sign)
            v = events.judge(res_val, "VAL", CRITERIA)
            extra = f" | VAL ex+1h={res_val.excess_by_horizon['+1h']:.4%} → {v}"
            if v == "keep_direction":
                verdict = "pass+VAL"
        hl.record_verdict(hid, "kill" if verdict == "kill" else "pass", {
            "train_excess": res.excess_by_horizon, "t_plus1h": res.t_by_horizon["+1h"],
            "n": res.n_events, "mfe_mae": res.mfe_mae_stats})
        ex = res.excess_by_horizon
        print(f"{hid:<32}{res.n_events:>7}{ex['+15m']:>9.4%}{ex['+1h']:>9.4%}"
              f"{ex['+4h']:>9.4%}{res.t_by_horizon['+1h']:>7.2f}{verdict:>10}{extra}")


if __name__ == "__main__":
    main()
