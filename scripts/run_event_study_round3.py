"""M2.5 — Event study đợt 3: các biến thể REVERSAL phát hiện từ đợt 2 (t-stat lớn chiều ngược).

Quy tắc: đợt 2 đo được t-stat lớn ở chiều ngược giả thuyết gốc → đăng ký giả thuyết MỚI
(với horizon/tiêu chí khai rõ TRƯỚC khi chạy), không được sửa tiêu chí giả thuyết cũ.

- H4a2_sell_surge_reversal_long  : taker sell surge (z ≤ −2) → SOL drift LÊN (mean reversion)
- H4a3_buy_surge_reversal_short  : taker buy surge (z ≥ +2) → SOL drift XUỐNG
- H4b2_fresh_money_reversal_short: OI↑ + giá↑ (tiền mới long) → SOL drift XUỐNG (exhaustion)
- H4d_oi_squeeze_long_4h         : squeeze quadrant (OI↓ + giá↑) → drift lên, horizon +4h
                                    (đợt 2: ex+4h 0.0835% nhưng tiêu chí cũ cố định +1h → kill;
                                    biến thể 4h là giả thuyết mới khai horizon rõ ràng)

Chạy: .venv/Scripts/python.exe scripts/run_event_study_round3.py
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

CRITERIA_1H = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
CRITERIA_4H = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+4h"}
SEGMENT = "TRAIN_2020-10_2023-06"


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()

    imb_z = ((sol["taker_imbalance_fast"] - sol["taker_imbalance_fast"].rolling(288).mean())
             / sol["taker_imbalance_fast"].rolling(288).std())
    imb_up = (imb_z >= 2).fillna(False)
    imb_dn = (imb_z <= -2).fillna(False)

    from solfut.features.orderflow import add_oi_context, load_oi
    oi = load_oi()
    sol_oi = add_oi_context(sol[["close"]].copy(), oi)
    q_fresh = (sol_oi["oi_quadrant"] == "oi_up_price_up")
    q_squeeze = (sol_oi["oi_quadrant"] == "oi_down_price_up")

    train = split_mask(sol.index, "TRAIN")
    val = split_mask(sol.index, "VAL")

    cases = [
        ("H4a2_sell_surge_reversal_long", imb_dn, 1, CRITERIA_1H, "M2.6 H4 OFI reversal (đợt 2: t=−6.08 chiều ngược)"),
        ("H4a3_buy_surge_reversal_short", imb_up, -1, CRITERIA_1H, "M2.6 H4 OFI reversal"),
        ("H4b2_fresh_money_reversal_short", q_fresh, -1, CRITERIA_1H, "M2.6 H4 OI reversal (đợt 2: t=−6.24)"),
        ("H4d_oi_squeeze_long_4h", q_squeeze, 1, CRITERIA_4H, "M2.6 H4 squeeze @4h (đợt 2: ex+4h 0.084%)"),
    ]
    print(f"{'hid':<34}{'n':>7}{'ex+1h':>9}{'ex+4h':>9}{'t':>7}{'verdict':>10}")
    for name, mask, sign, crit, source in cases:
        hl.register(name, name, source, crit, SEGMENT)
        res = events.run_event_study(sol, mask & train, name, sign=sign)
        verdict = events.judge(res, "TRAIN", crit)
        extra = ""
        if verdict == "pass":
            res_val = events.run_event_study(sol, mask & val, name, sign=sign)
            v = events.judge(res_val, "VAL", crit)
            ex_v = res_val.excess_by_horizon[crit["horizon"]]
            extra = f" | VAL {crit['horizon']}={ex_v:.4%} → {v}"
            if v == "keep_direction":
                verdict = "pass+VAL"
        hl.record_verdict(name, "kill" if verdict == "kill" else "pass", {
            "train_excess": res.excess_by_horizon,
            "t": res.t_by_horizon[crit["horizon"]],
            "n": res.n_events, "mfe_mae": res.mfe_mae_stats})
        ex = res.excess_by_horizon
        t = res.t_by_horizon[crit["horizon"]]
        print(f"{name:<34}{res.n_events:>7}{ex['+1h']:>9.4%}{ex['+4h']:>9.4%}{t:>7.2f}{verdict:>10}{extra}")


if __name__ == "__main__":
    main()
