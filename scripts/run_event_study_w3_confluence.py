"""WAVE 3 — Confluence của các giả thuyết ĐÃ PASS (cấu trúc, không phải grid tham số):

H3W_confluence_long = H2b trigger (BTC 5m ≤ −2σ96) × gate vol TUYỆT ĐỐI (atr14_5m > 2×
anchor 0.20% từ settings.market_anchor — hằng số đo 2026-09-19, KHÔNG fit TRAIN) ×
premium rank 30d < 0.25 (nửa stress của H5b).

Căn cứ mechanism a-priori: bounce sau forced selling cần (1) forced flow (BTC jump),
(2) market đang stress thật (vol tuyệt đối cao — atrPct tương đối đã thất bại VAL vì
trong grind 30d vẫn có rank>0.7), (3) perp đang dưới áp lực short (premium thấp).
Confluence 3 tín hiệu độc lập về nguồn (BTC price / SOL vol / SOL basis).

=== PRE-REGISTERED criteria (TRƯỚC KHI ĐO — segment WAVE2, cap 30) ===
- excess @+4h ≥ +0.55%  — con số từ phép tính kill của Wave 1: cần drift×capture − RT
  > 0.05×sl → drift ≥ 0.55% với sl~7%, capture~70% (nếu không đạt → không đáng backtest).
- t ≥ 3; moving-block CI95 (block=48) của excess > 0.
- VAL 2023-07→2024-06 giữ hướng @4h (excess dương).
- n ≥ 200 (luật 3).
KILL nếu thiếu bất kỳ.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w3_confluence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.config import settings
from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HORIZONS = {"+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}
HID = "H3W_confluence_long"

# criteria pre-registered
EX4H_MIN = 0.0055
T_MIN = 3.0
N_MIN = 200


def main() -> None:
    hl.register(hid=HID,
                name="H3W confluence: BTC-jump × atr>2×anchor(0.40% tuyệt đối) × premium<0.25 → "
                     "long — 3 nguồn độc lập (BTC price / SOL vol / SOL basis)",
                source="Confluence của H2b (PASS) + H5b (PASS) + absolute-vol gate (luật 20 lớp horizon)",
                criteria={"excess_4h_min": EX4H_MIN, "t_min": T_MIN, "ci_gt": 0.0,
                          "n_min": N_MIN, "val_keep_direction_4h": True},
                segment="WAVE2_2020-10_2023-06")

    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]

    # H2b trigger
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    ret = btc["close"].pct_change()
    btc_jump = (ret <= -2 * ret.rolling(96).std()).reindex(sol.index).fillna(False)

    # absolute vol gate: atr14(5m) > 2 × anchor
    anchor_atr = settings()["market_anchor"]["atr14_m5_pct"] / 100
    atr_gate = sol["atr14"] > 2 * anchor_atr

    # premium rank (H5b stress half)
    prem = pd.read_parquet(DATA_DIR / "premium" / "SOLUSDT_premium_5m.parquet")["premium"]
    p_rank = prem.reindex(sol.index).rolling(8640, min_periods=2880).rank(pct=True)
    prem_low = p_rank.lt(0.25).fillna(False)

    mask = btc_jump & atr_gate & prem_low
    train_mask = (sol.index >= T_START) & (sol.index <= T_END)
    ev_idx = sol.index[mask & train_mask]
    logger.info(f"H3W events TRAIN: {len(ev_idx)} "
                f"(H2b alone {int((btc_jump & train_mask).sum())}, "
                f"+atr {int((btc_jump & atr_gate & train_mask).sum())}, "
                f"+premium {len(ev_idx)})")

    res = events.run_event_study(sol, mask, HID, horizons=HORIZONS)
    ex4 = res.excess_by_horizon.get("+4h")
    t4 = res.t_by_horizon.get("+4h")
    ci4 = res.ci_event_by_horizon.get("+4h", {})
    lo4 = ci4.get("lo")

    # VAL giữ hướng @4h
    fwd4 = sol["close"].shift(-48) / sol["close"] - 1
    val_mask = mask & (sol.index > T_END) & (sol.index <= V_END)
    ev_val = fwd4.loc[sol.index[val_mask]].dropna()
    base_val = float(fwd4[(sol.index > T_END) & (sol.index <= V_END)].dropna().mean())
    val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 50 else float("nan")

    ok = bool(len(ev_idx) >= N_MIN and ex4 == ex4 and ex4 >= EX4H_MIN
              and t4 == t4 and t4 >= T_MIN and lo4 == lo4 and lo4 is not None and lo4 > 0
              and val_ex == val_ex and val_ex > 0)
    result = {
        "n_events": int(res.n_events),
        "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
        "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
        "ci95_4h": [ci4.get("lo"), ci4.get("hi")],
        "mfe_mae": res.mfe_mae_stats,
        "val_excess_4h": val_ex,
        "criteria": {"ex4h_min": EX4H_MIN, "t_min": T_MIN, "n_min": N_MIN},
    }
    hl.record_verdict(HID, "pass" if ok else "kill", result)
    logger.info(f"H3W: ex@1h={res.excess_by_horizon['+1h']*100:+.3f}% ex@4h={ex4*100 if ex4==ex4 else float('nan'):+.3f}% "
                f"t@4h={t4} ex@8h={res.excess_by_horizon['+8h']*100:+.3f}% ex@24h={res.excess_by_horizon['+24h']*100:+.3f}%")
    logger.info(f"CI95@4h=[{lo4},{ci4.get('hi')}] MFE/MAE={res.mfe_mae_stats} val@4h={val_ex*100:+.3f}% n_val={len(ev_val)}")
    logger.info(f"VERDICT: {'pass' if ok else 'kill'}")
    out = DATA_DIR / "reports" / "w3_confluence.json"
    out.write_text(json.dumps({"verdict": "pass" if ok else "kill", "result": result},
                              indent=1, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
