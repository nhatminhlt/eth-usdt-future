"""M2.6 H6 — Funding-carry Track B: event-study feasibility trên FULL funding history (PLAN 4c H6).

Cấu trúc: long spot SOL + short perp SOLUSDT (delta-neutral) khi funding cao → thu funding mỗi kỳ
settle; exit khi funding về median. PnL pair = Σ funding nhận (short perp) − chi phí vào/ra.
Là giả thuyết DUY NHẤT trong menu chịu phí tốt theo cấu trúc (chi phí RT ~0.24% amortise trên
lệnh giữ nhiều ngày) — đúng thứ mà V1 chết vì thiếu.

=== PRE-REGISTERED (viết trước khi chạy — ledger luật 13) ===
Cơ chế state machine trên funding marks (timestamp THẬT từng kỳ — luật 17):
- Enter pair khi: funding rate của mark vừa settle ≥ T_hi = p90 của 270 mark trailing (90 ngày),
  đang flat, đủ 100 mark lịch sử.
- Exit khi: funding rate của mark < T_lo = median của 270 mark trailing → đóng pair NGAY SAU mark đó
  (vẫn NHẬN funding của mark đó nếu đang giữ — mark giữ tại thời điểm settle được nhận).
- Thu nhập 1 cycle (fraction notional): Σ rate của các mark trong (enter_mark, exit_mark].
- Chi phí 1 cycle: 0.24% notional (spot+perp vào/ra 4 fill — con số tham chiếu PLAN M2.6 H6).
- Net cycle = thu nhập − chi phí.

Tiêu chí PASS (TRAIN 2020-10-01→2023-06-30):
  (1) n_cycles ≥ 3;
  (2) median net cycle > +0.2% notional;
  (3) bootstrap CI 95% (10k lần, resample cycle) của mean net > 0;
  (4) worst cycle ≥ −0.5% (pair hedged — funding flip không được phép nuốt cycle);
  (5) tổng thời gian giữ ≥ 30 ngày (không phải 1 event duy nhất).
KILL nếu thiếu bất kỳ điều kiện trên.

Segment: TRAIN_2020-10_2023-06. VAL sẽ confirm sau nếu pass (không chấm ở script này).

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h6_carry.py
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
from solfut.research import hypotheses as hl

SEGMENT = "TRAIN_2020-10_2023-06"
T_START, T_END = pd.Timestamp("2020-10-01", tz="UTC"), pd.Timestamp("2023-06-30 23:59", tz="UTC")
WINDOW = 270            # trailing 90 ngày × 3 mark/ngày (8h) — theo mark THỰC, không giả định 8h
COST_RT = 0.0024        # 0.24% RT spot+perp
HID = "H6_carry_feasibility"


def run_state_machine(rates: pd.Series, t_start: pd.Timestamp, t_end: pd.Timestamp,
                      window: int = WINDOW, cost_rt: float = COST_RT,
                      hi_floor: float = 0.0, lo_floor: float = 0.0) -> pd.DataFrame:
    """rates: Series rate theo mark time (UTC, sorted). Chỉ dùng mark trong [t_start, t_end]
    để RA QUYẾT ĐỊNH; trailing quantile tính trên lịch sử trước mỗi mark (không lookahead).
    hi_floor/lo_floor: sàn TUYỆT ĐỐI cho threshold (variant absfloor — 0 = thuần percentile)."""
    r = rates.sort_index()
    hist = r[r.index < t_end]
    pos = hist.index.searchsorted(t_start)
    cycles = []
    holding = False
    enter_mark = None
    income = 0.0
    for i in range(pos, len(hist)):
        ts = hist.index[i]
        rate = float(hist.iloc[i])
        past = hist.iloc[max(0, i - window):i]
        if len(past) < 100:
            continue
        t_hi = max(float(past.quantile(0.90)), hi_floor)
        t_lo = max(float(past.quantile(0.50)), lo_floor)
        if not holding and rate >= t_hi:
            holding, enter_mark, income = True, ts, 0.0
            continue
        if holding:
            income += rate                       # mark settle khi đang giữ → nhận/trả
            if rate < t_lo:                      # exit ngay sau mark này
                n_marks = int(((hist.index > enter_mark) & (hist.index <= ts)).sum())
                cycles.append({"enter": enter_mark, "exit": ts,
                               "marks_held": n_marks,
                               "income": income, "cost": cost_rt, "net": income - cost_rt,
                               "days": (ts - enter_mark).total_seconds() / 86400})
                holding = False
    return pd.DataFrame(cycles)


def main() -> None:
    # ===== VARIANT 2 (pre-register TRƯỚC KHI TÍNH — idempotent): sàn tuyệt đối =====
    # Căn cứ KINH TẾ viết TRƯỚC: RT 0.24% phải amortise bằng dòng funding khi giữ.
    # Floor vào 0.02%/mark (≈2.2%/năm gross khi giữ) — gấp ~8× RT cần ~12 mark (4 ngày) hồi vốn;
    # floor thoát 0.01%/mark (nửa floor vào). KHÔNG grid thêm — 1 variant duy nhất, kết quả
    # variant 1 (percentile thuần) đã KILL vì churn 2022-23 (132 cycle, median −0.23%).
    HID2 = "H6_carry_absfloor"
    HI_FLOOR, LO_FLOOR = 0.0002, 0.0001
    hl.register(hid=HID2,
                name="H6 Track B carry — variant sàn tuyệt đối (enter ≥ max(p90, 0.02%/mark), "
                     "exit < max(median, 0.01%/mark))",
                source="M2.6 H6 revision: variant 1 (percentile thuần) KILL — churn 2022-23, "
                       "RT 0.24% không amortise ở cycle 2.9 ngày; floor tuyệt đối = điều kiện "
                       "kinh tế 'funding tự nó trả chi phí'",
                criteria={"same_as": HID, "note": "cùng 5 tiêu chí pre-registered của H6 gốc"},
                segment=SEGMENT)

    df = pd.read_parquet(DATA_DIR / "funding" / "SOLUSDT_funding.parquet")
    df["ts"] = pd.to_datetime(df["fundingTime"], utc=True, unit="ms")
    rates = df.set_index("ts")["fundingRate"].astype(float).sort_index()

    # bối cảnh: phân phối funding theo năm (attribution, không phải gate)
    ctx = rates.groupby(rates.index.year).agg(
        n="size", mean="mean", median="median",
        p90=lambda x: x.quantile(0.9), p99=lambda x: x.quantile(0.99),
        neg_share=lambda x: float((x < 0).mean()))
    logger.info(f"Phân phối funding theo năm (fraction/kỳ):\n{ctx}")

    cyc = run_state_machine(rates, T_START, T_END, hi_floor=HI_FLOOR, lo_floor=LO_FLOOR)
    logger.info(f"[absfloor] Cycles TRAIN: {len(cyc)}")
    if len(cyc):
        logger.info(f"\n{cyc[['enter', 'days', 'income', 'net']].to_string()}")

    res: dict = {"segment": SEGMENT, "variant": "absfloor",
                 "mechanism": f"enter ≥ max(trailing-90d p90, {HI_FLOOR}), exit < max(median, {LO_FLOOR})",
                 "n_cycles": int(len(cyc)), "context_by_year": json.loads(ctx.to_json())}
    if len(cyc) == 0:
        verdict = "kill"
        res.update({"reason": "0 cycle trong TRAIN"})
    else:
        net = cyc["net"].to_numpy(float)
        rng = np.random.default_rng(42)
        boots = [float(rng.choice(net, len(net), replace=True).mean()) for _ in range(10_000)]
        lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
        total_days = float(cyc["days"].sum())
        cyc_year = pd.to_datetime(cyc["enter"]).dt.year
        by_year = cyc.groupby(cyc_year)["net"].agg(["sum", "count", "median"])
        res.update({
            "median_net_cycle": float(np.median(net)),
            "mean_net_cycle": float(net.mean()),
            "worst_cycle": float(net.min()),
            "best_cycle": float(net.max()),
            "ci95_mean_net": [lo, hi],
            "total_holding_days": total_days,
            "total_income_pct": float(net.sum()) * 100,
            "avg_days_per_cycle": float(cyc["days"].mean()),
            "by_year": json.loads(by_year.rename(columns={"sum": "net_sum", "count": "n",
                                                          "median": "net_median"}).to_json()),
        })
        ok = {
            "n_cycles": len(cyc) >= 3,
            "median_net": res["median_net_cycle"] > 0.002,
            "ci_gt_zero": lo > 0,
            "worst_cycle": res["worst_cycle"] >= -0.005,
            "holding_days": total_days >= 30,
        }
        res["criteria_check"] = {k: bool(v) for k, v in ok.items()}
        verdict = "pass" if all(ok.values()) else "kill"
        logger.info(f"Criteria: {res['criteria_check']} → {verdict}")
        logger.info(json.dumps({k: v for k, v in res.items() if k != 'context_by_year'},
                               indent=1, ensure_ascii=False, default=str))

    hl.record_verdict(HID2, verdict, res)
    out = DATA_DIR / "reports" / "m2_6_h6_carry_absfloor.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
