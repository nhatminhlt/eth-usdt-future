"""W6a — Event-study 3 atom MỚI từ 4 tài liệu exp/ của user (Làn A). Pre-registered TRƯỚC KHI ĐO.

- H11_wick_sweep_fade_long (qwen §12 quét thanh khoản + deepseek "wicks quét SL"):
    nến có low < min(low, 48 bar trước) NHƯNG close > đáy cũ (râu xuyên đáy, đóng lại trong
    range) → drift LÊN. Entry bar cụ thể (khác H10b close-based) — ứng viên sửa lỗi
    episode-cluster timing của H9. Criteria M2.5 mặc định: excess ≥ 0.05% @+1h, t ≥ 2, CI > 0.
- H13_squeeze_fade_short (deepseek cảnh báo #1: giá↑ + OI↓ = squeeze "hết nhiên liệu"):
    event = bar CHUYỂN vào góc phần tư oi_down_price_up (định nghĩa GIỐNG H4d/C-strategy,
    transition-only), đo drift XUỐNG (sign=−1). Horizon pre-registered +4h (anchor từ phép
    đo H4d cùng event-def — tránh chọn sau khi thấy).
- H12_vwap_stretch_fade_long (qwen chiến lược 5 day-trade VWAP):
    VWAP reset mỗi ngày UTC 00:00 từ 5m (typical price × volume); dev = (close−vwap)/close;
    z = dev / std(dev, trailing 30 ngày); event z ≤ −2 → drift LÊN (về VWAP).
    Criteria M2.5 mặc định @+1h.

TRAIN = 2020-10-01→2023-06-30 (gate); VAL = 2023-07-01→2024-06-30 (giữ hướng).
Ledger: segment WAVE3_2020-10_2025-08. OI chỉ có từ 2021-12 (metrics) — H13 đo trên phần
data có OI, n thật sẽ ghi nhận.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_w6_exp_atoms.py
Output: data/reports/w6_exp_atoms.json
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
from solfut.features.orderflow import add_oi_context, load_oi
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
SEG = "WAVE3_2020-10_2025-08"
HORIZONS = {"+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}
DEFAULT = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]

    # ---------- masks (định nghĩa chốt trước khi đo) ----------
    low48 = sol["low"].rolling(48).min().shift(1)
    h11_mask = ((sol["low"] < low48) & (sol["close"] > low48)).fillna(False)

    oi = load_oi()
    sol_oi = add_oi_context(sol[["close"]].copy(), oi)
    in_sq = (sol_oi["oi_quadrant"] == "oi_down_price_up")
    h13_mask = in_sq & ~in_sq.shift(1, fill_value=False)

    day = sol.index.floor("D")
    tp = (sol["high"] + sol["low"] + sol["close"]) / 3.0
    pv = (tp * sol["volume"]).groupby(day).cumsum()
    vv = sol["volume"].groupby(day).cumsum().replace(0, np.nan)
    vwap = pv / vv
    dev = (sol["close"] - vwap) / sol["close"]
    z = dev / dev.rolling(8640, min_periods=2880).std()
    h12_mask = z.le(-2).fillna(False)

    # ---------- PRE-REGISTER 3 rows TRƯỚC ----------
    hl.register(hid="H11_wick_sweep_fade_long",
                name="H11 wick-sweep fade: low xuyên đáy 48-bar + close quay lại range → long "
                     "(entry bar cụ thể — sửa timing H9)",
                source="exp/qwen.json §12 + exp/deepseek.md (feed user, luật 16)",
                criteria=dict(DEFAULT), segment=SEG)
    hl.register(hid="H13_squeeze_fade_short",
                name="H13 squeeze-fade SHORT: chuyển vào góc OI↓+giá↑ → drift XUỐNG "
                     "(giá↑ trên OI↓ = squeeze thiếu nhiên liệu)",
                source="exp/deepseek.md cảnh báo #1; event-def GIỐNG H4d, sign −1; "
                       "horizon +4h anchor từ H4d",
                criteria={"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+4h"},
                segment=SEG)
    hl.register(hid="H12_vwap_stretch_fade_long",
                name="H12 VWAP-stretch fade: z(close−vwap, 30 ngày) ≤ −2 → drift LÊN về VWAP",
                source="exp/qwen.json chiến lược 5 (day-trade VWAP)",
                criteria=dict(DEFAULT), segment=SEG)

    report: dict = {"segment": SEG, "source": "exp/ 4 tài liệu user — Làn A"}
    for hid, mask, sign, horizon in (
            ("H11_wick_sweep_fade_long", h11_mask, +1, "+1h"),
            ("H13_squeeze_fade_short", h13_mask, -1, "+4h"),
            ("H12_vwap_stretch_fade_long", h12_mask, +1, "+1h")):
        train_mask = (sol.index >= T_START) & (sol.index <= T_END)
        ev_idx = sol.index[mask & train_mask]
        res = events.run_event_study(sol, mask, hid, horizons=HORIZONS, sign=sign)
        ex = res.excess_by_horizon.get(horizon)
        t = res.t_by_horizon.get(horizon)
        ci = res.ci_event_by_horizon.get(horizon, {})
        lo = ci.get("lo")
        ok = bool(ex == ex and ex >= 0.0005 and t == t and t >= 2.0
                  and lo == lo and lo is not None and lo > 0)
        # VAL giữ hướng tại horizon đã đăng ký
        hbars = HORIZONS[horizon]
        fwd = sol["close"].shift(-hbars) / sol["close"] - 1
        val_mask = mask & (sol.index > T_END) & (sol.index <= V_END)
        ev_val = (sign * fwd).loc[sol.index[val_mask]].dropna()
        base_val = float((sign * fwd)[(sol.index > T_END) & (sol.index <= V_END)].dropna().mean())
        val_ex = float(ev_val.mean() - base_val) if len(ev_val) >= 100 else float("nan")
        val_ok = bool(val_ex == val_ex and val_ex > 0)
        verdict = "pass" if (ok and val_ok) else "kill"
        result = {
            "n_events": int(res.n_events),
            "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
            "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
            "ci95": [lo, ci.get("hi")],
            "mfe_mae": res.mfe_mae_stats,
            "val_excess": val_ex, "val_n": int(len(ev_val)),
        }
        hl.record_verdict(hid, verdict, result)
        report[hid] = {"verdict": verdict, "result": result}
        logger.info(f"{hid}: n={res.n_events} ex@{horizon}={ex*100 if ex==ex else float('nan'):+.3f}% "
                    f"t={t:.2f} CIlo={lo} val={val_ex*100:+.3f}% (n={len(ev_val)}) → {verdict}")
        logger.info(f"    decay: " + " ".join(
            f"{k}={v*100:+.3f}%" for k, v in res.excess_by_horizon.items()))

    out = DATA_DIR / "reports" / "w6_exp_atoms.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
