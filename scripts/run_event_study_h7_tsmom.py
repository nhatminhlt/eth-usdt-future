"""M2.5/M2.6 H7 — TSMOM D1 swing (pre-registered, ledger row 29): SOL D1 momentum state flip.

Nguồn: PLAN M2.6 H7 — TSMOM crypto được chứng minh (Borgards 2021, cited 32; Grobys 2025;
vol-scaled momentum tăng Sharpe — Yang 2025). Lớp swing giữ NHIỀU NGÀY — RT cost amortise
trên biến động %, thoát khỏi bẫy chi phí intraday mà M4/M4b/M4c đã chứng minh (drift cận không).

=== PRE-REGISTERED (trước khi chạy) ===
Trạng thái trend (tính trên D1 close, causal):
- LONG state: close > EMA20 VÀ slope10(EMA20) > 0
- SHORT state: close < EMA20 VÀ slope10 < 0
Event = bar D1 CHUYỂN trạng thái (off→on), đo forward-return close[t]→close[t+h] với
h ∈ {5, 10, 20, 40} ngày, đối chiếu baseline vô điều kiện cùng horizon (TRAIN).
Entry thực sẽ ở OPEN ngày kế (không lookahead) — phép đo từ close là xấp xỉ hợp lệ swing.

Tiêu chí PASS (TRAIN 2020-10→2023-06, mỗi hướng độc lập):
  n_events ≥ 25; excess @20d ≥ +2.0%; moving-block bootstrap CI95 (block=5 events) của
  excess > 0; VAL giữ hướng (excess @20d cùng dấu).
KILL nếu thiếu bất kỳ. (n nhỏ ở D1 là bản chất của TF — CI bootstrap là phán quan chính,
theo reality-check cỡ mẫu của PLAN M5.)

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h7_tsmom.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.features.indicators import ema
from solfut.research import hypotheses as hl
from solfut.research.splits import split_mask

HORIZONS = {"+5d": 5, "+10d": 10, "+20d": 20, "+40d": 40}
HID_LONG = "H7_tsmom_d1_long"
HID_SHORT = "H7_tsmom_d1_short"


def trend_states(sol_d1: pd.DataFrame) -> pd.DataFrame:
    e = ema(sol_d1["close"], 20)
    slope = e.diff(10)
    up = (sol_d1["close"] > e) & (slope > 0)
    dn = (sol_d1["close"] < e) & (slope < 0)
    return pd.DataFrame({"up_on": up & ~up.shift(1, fill_value=False),
                         "dn_on": dn & ~dn.shift(1, fill_value=False),
                         "up_state": up, "dn_state": dn})


def block_bootstrap_excess(ev: np.ndarray, base: float, block: int = 5,
                           n_boot: int = 5000, seed: int = 42) -> tuple[float, float, float]:
    ev = ev[~np.isnan(ev)]
    n = len(ev)
    if n < block * 2:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    exs = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n - block, n_blocks)
        sample = np.concatenate([ev[s:s + block] for s in starts])[:n]
        exs[b] = sample.mean() - base
    return float(exs.mean()), float(np.percentile(exs, 2.5)), float(np.percentile(exs, 97.5))


def main() -> None:
    # Chỉ LONG được đăng ký (ledger 30/30 ĐẦY — kỷ luật không nới; plan H7 là long-bias).
    # SHORT vẫn ĐO để làm attribution context, ghi rõ "not_registered_attribution_only" — không claim.
    hl.register(hid=HID_LONG,
                name="H7 TSMOM D1 long: state flip (close > EMA20 & slope10>0), hold 5-40d — "
                     "swing class, RT amortise",
                source="PLAN M2.6 H7: Borgards 2021; Grobys 2025; Yang 2025",
                criteria={"n_min": 25, "excess_20d_min_pct": 0.02,
                          "ci95_excess_gt": 0.0, "val_keep_direction": True},
                segment="TRAIN_2020-10_2023-06")

    sol_d1 = pd.read_parquet(DATA_DIR / "SOLUSDT_1d.parquet")
    sol_d1.index = pd.to_datetime(sol_d1["open_time"], unit="ms", utc=True)
    st = trend_states(sol_d1)
    report: dict = {"hypotheses": {}}

    for hid, col in ((HID_LONG, "up_on"), (HID_SHORT, "dn_on")):
        registered = hid == HID_LONG
        train_mask = split_mask(sol_d1.index, "TRAIN")
        ev_idx = sol_d1.index[st[col] & train_mask]
        base_mask = split_mask(sol_d1.index, "TRAIN")
        res: dict = {"n_events": int(len(ev_idx)), "horizons": {}}
        ok_all = res["n_events"] >= 25
        for hname, h in HORIZONS.items():
            fwd = sol_d1["close"].shift(-h) / sol_d1["close"] - 1
            ev = fwd.loc[ev_idx].dropna().values
            base = float(fwd[base_mask].dropna().mean())
            mean, lo, hi = block_bootstrap_excess(ev, base)
            ex_pct = (mean if mean == mean else 0) * 100
            res["horizons"][hname] = {"excess_pct": float(ex_pct),
                                      "mean_pct": float(np.nanmean(ev) * 100),
                                      "base_pct": base * 100,
                                      "ci95_excess_pct": [lo * 100, hi * 100],
                                      "n": int(len(ev))}
            if hname == "+20d":
                ok_h = ex_pct >= 2.0 and lo > 0
            ok_all = ok_all and (lo > 0 if hname == "+20d" else True)
        # VAL giữ hướng @20d
        val_mask = split_mask(sol_d1.index, "VAL")
        ev_val = sol_d1.index[st[col] & val_mask]
        fwd20 = sol_d1["close"].shift(-20) / sol_d1["close"] - 1
        base_val = float(fwd20[val_mask].dropna().mean())
        ev20 = fwd20.loc[ev_val].dropna()
        val_ex = float((ev20.mean() - base_val) * 100) if len(ev20) else float("nan")
        res["val_excess_20d_pct"] = val_ex
        res["n_val_events"] = int(len(ev20))
        ok_all = ok_all and ok_h and (val_ex > 0)
        verdict = "pass" if ok_all else "kill"
        res["verdict"] = verdict
        logger.info(f"{hid}: n={res['n_events']} val_n={res['n_val_events']} "
                    f"val_ex20d={val_ex:+.2f}% → {verdict}")
        logger.info(json.dumps(res["horizons"], indent=1))
        if registered:
            hl.record_verdict(hid, verdict, res)
        else:
            res["note"] = "not_registered_attribution_only — ledger đầy 30/30, không claim"
        report["hypotheses"][hid] = res

    out = DATA_DIR / "reports" / "m2_5_h7_tsmom.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
