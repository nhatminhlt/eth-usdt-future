"""W4b — H10b: fade-the-breakdown (H10 của Gate Wiki bị dữ liệu PHỦ ĐỊNH chiều short:
sau breakdown 48-bar + volume, giá drift LÊN +0.143% @1h t=6.65, VAL cùng hướng +0.065%).
Đăng ký lại đúng chiều dữ liệu → long. Criteria giữ nguyên M2.5 mặc định.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w4b_h10b.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HORIZONS = {"+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}
CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
HID = "H10b_breakdown_fade_long"


def main() -> None:
    hl.register(hid=HID,
                name="H10b fade-the-breakdown: 48-bar low break + volume 1.5× → drift LÊN "
                     "(H10 short của Gate Wiki bị dữ liệu phủ định — đảo chiều theo measurement)",
                source="H10 refutation (w4_gate_atoms.json) — chiều long, criteria M2.5",
                criteria=dict(CRITERIA), segment="WAVE3_2020-10_2025-08")

    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]
    low48 = sol["low"].rolling(48).min().shift(1)
    vol_sma48 = sol["volume"].rolling(48).mean().shift(1)
    mask = ((sol["close"] < low48) & (sol["volume"] > 1.5 * vol_sma48)).fillna(False)

    res = events.run_event_study(sol, mask, HID, horizons=HORIZONS, sign=+1)
    ex1 = res.excess_by_horizon.get("+1h")
    t1 = res.t_by_horizon.get("+1h")
    ci1 = res.ci_event_by_horizon.get("+1h", {})
    lo1 = ci1.get("lo")
    ok = bool(ex1 == ex1 and ex1 >= 0.0005 and t1 == t1 and t1 >= 2.0
              and lo1 == lo1 and lo1 is not None and lo1 > 0)
    fwd1 = sol["close"].shift(-12) / sol["close"] - 1
    val_mask = mask & (sol.index > T_END) & (sol.index <= V_END)
    ev_val = fwd1.loc[sol.index[val_mask]].dropna()
    base_val = float(fwd1[(sol.index > T_END) & (sol.index <= V_END)].dropna().mean())
    val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 100 else float("nan")
    val_ok = bool(val_ex == val_ex and val_ex > 0)
    result = {
        "n_events": int(res.n_events),
        "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
        "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
        "ci95_1h": [ci1.get("lo"), ci1.get("hi")],
        "mfe_mae": res.mfe_mae_stats,
        "val_excess_1h": val_ex, "val_keep_direction": val_ok,
    }
    verdict = "pass" if (ok and val_ok) else "kill"
    hl.record_verdict(HID, verdict, result)
    logger.info(f"{HID}: n={res.n_events} ex@1h={ex1*100:+.3f}% t@1h={t1} "
                f"ex@4h={res.excess_by_horizon['+4h']*100:+.3f}% ex@8h={res.excess_by_horizon['+8h']*100:+.3f}% "
                f"val@1h={val_ex*100:+.3f}% → {verdict}")
    out = DATA_DIR / "reports" / "w4b_h10b.json"
    out.write_text(json.dumps({"verdict": verdict, "result": result}, indent=1,
                              ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
