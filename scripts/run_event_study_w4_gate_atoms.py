"""W4 — Hai atom codable từ practitioner source (Gate Wiki SOL/USDT TA article — claim không
backtest; replication trên dữ liệu là phán quan duy nhất, PLAN 4c.1/luật 16):

- H9_rsi_oversold_long: RSI(14) 5m < 30 → drift LÊN (bounce quá bán). Cùng họ fade đã đo
  (excess kỳ vọng 0.05–0.3%); criteria pre-registered giống M2.5 mặc định.
- H10_breakdown_short: 5m close < min(low, 48 bar) + volume bar break > 1.5× SMA48 volume
  → drift XUỐNG (lớp momentum breakdown — hướng TRÁI chưa từng test trong ledger).
  sign=−1; criteria pre-registered giống M2.5 mặc định (excess ≥ 0.05% @+1h theo chiều short).

Segment WAVE3_2020-10_2025-08 (nguồn thông tin: giá/volume — nhưng atom mới, source mới).
VAL 2023-24 giữ hướng. Block bootstrap, MFE/MAE ghi nhận cho derive nếu pass.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w4_gate_atoms.py
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
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HORIZONS = {"+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}
CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]
    seg = "WAVE3_2020-10_2025-08"

    # --- H9: RSI(14) < 30 (RSI đã có sẵn trong enriched)
    rsi = sol["rsi14"]
    h9_mask = rsi.lt(30).fillna(False)

    # --- H10: breakdown 48-bar low + volume confirmation → SHORT
    low48 = sol["low"].rolling(48).min().shift(1)     # đáy 48 bar TRƯỚC (không lookahead)
    vol_sma48 = sol["volume"].rolling(48).mean().shift(1)
    h10_mask = (sol["close"] < low48) & (sol["volume"] > 1.5 * vol_sma48)
    h10_mask = h10_mask.fillna(False)

    report: dict = {"segment": seg, "source": "Gate Wiki SOL/USDT TA article (2026-01-02)"}
    for hid, mask, sign in (("H9_rsi_oversold_long", h9_mask, +1),
                            ("H10_breakdown_short", h10_mask, -1)):
        hl.register(hid=hid,
                    name=f"{hid}: atom từ Gate Wiki article — RSI<30 bounce / 48-bar breakdown short",
                    source="Gate Wiki practitioner article (no backtest) — replication gate",
                    criteria=dict(CRITERIA), segment=seg)
        train_mask = (sol.index >= T_START) & (sol.index <= T_END)
        res = events.run_event_study(sol, mask, hid, horizons=HORIZONS, sign=sign)
        ex1 = res.excess_by_horizon.get("+1h")
        t1 = res.t_by_horizon.get("+1h")
        ci1 = res.ci_event_by_horizon.get("+1h", {})
        lo1 = ci1.get("lo")
        ok = bool(ex1 == ex1 and ex1 >= 0.0005 and t1 == t1 and t1 >= 2.0
                  and lo1 == lo1 and lo1 is not None and lo1 > 0)
        # VAL giữ hướng
        fwd1 = sol["close"].shift(-12) / sol["close"] - 1
        val_mask = mask & (sol.index > T_END) & (sol.index <= V_END)
        ev_val = (sign * fwd1).loc[sol.index[val_mask]].dropna()
        base_val = float((sign * fwd1)[(sol.index > T_END) & (sol.index <= V_END)].dropna().mean())
        val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 100 else float("nan")
        val_ok = bool(val_ex == val_ex and val_ex > 0)
        result = {
            "n_events": int(res.n_events), "sign": sign,
            "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
            "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
            "ci95_1h": [ci1.get("lo"), ci1.get("hi")],
            "mfe_mae": res.mfe_mae_stats,
            "val_excess_1h": val_ex, "val_keep_direction": val_ok,
        }
        verdict = "pass" if (ok and val_ok) else "kill"
        hl.record_verdict(hid, verdict, result)
        report[hid] = {"verdict": verdict, "result": result}
        logger.info(f"{hid}: n={res.n_events} ex@1h={ex1*100 if ex1==ex1 else float('nan'):+.3f}% "
                    f"t@1h={t1} ex@4h={res.excess_by_horizon['+4h']*100:+.3f}% "
                    f"val@1h={val_ex*100:+.3f}% → {verdict}")

    out = DATA_DIR / "reports" / "w4_gate_atoms.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
