"""W6b — H12 VWAP-stretch: (1) attributed episode-timing (measure-only) + (2) implementation
pre-registered cho ENTRY-BAR-ĐẦU nếu timing tradeable.

Bài học 21 (H9): drift của event với label chồng lấn có thể thuộc bar sâu giữa episode.
H12 z≤−2 là chuỗi bar liên tục trong đợt dump → kiểm tra phân rã theo vị trí episode:
  - event_first: mask & ~mask.shift(12, fill False-fill proxy: z>−2 trong 12 bar trước)
  - event_later: mask & (z ≤ −2 từng bar trong 12 bar trước)
Chỉ event_first là tradeable với engine (một signal/episode; các bar sau còn trễ hoặc dính).

PRE-REGISTERED cấu hình implementation (TRƯỚC KHI CHẠY — chỉ chạy nếu measure-only cho thấy
bar đầu có excess@4h > 0):
- Trigger: z ≤ −2 VÀ z > −2 mọi bar trong 1h trước (entry đầu đợt) — atom cụ thể "stretch
  vừa chạm cực đoan", không phải "đã stretch lâu".
- Entry: maker post-only low event bar (trade-through) KIÊM taker-entry đối chiếu.
- Holding 48 bar (ex @4h +0.568% FULL mask; bar đ& đợt nếu timing tốt sẽ cao hơn).
- SL thiên tai = |MAE q05| của event_first TRAIN; partial_pct = median MFE event_first TRAIN
  (partial-BE engine — cấu hình đã chuẩn hóa W4).
- governed cap 3% lev 1×; maker/maker kịch bản chính; flat-EOD; funding thật.
- Gate: settings.gates trên TRAIN; VAL chấm expectancy cùng dấu.

Chạy: .venv/Scripts/python.exe scripts/run_w6_h12_impl.py
Output: data/reports/w6_h12_impl.json (+ ledger verdict H12_impl nếu chạy đến đó)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.backtest.costs import FundingSchedule, load_cost_model
from solfut.backtest.engine import run_backtest
from solfut.backtest.metrics import bootstrap_expectancy_ci, compute_metrics, gates_check
from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START = pd.Timestamp("2023-07-01", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
HOLDING = 48
HID_IMPL = "H12_impl_vwap_stretch_first"


def build(sol: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    day = sol.index.floor("D")
    tp = (sol["high"] + sol["low"] + sol["close"]) / 3.0
    vwap = (tp * sol["volume"]).groupby(day).cumsum() / \
        sol["volume"].groupby(day).cumsum().replace(0, np.nan)
    dev = (sol["close"] - vwap) / sol["close"]
    z = dev / dev.rolling(8640, min_periods=2880).std()
    mask = z.le(-2).fillna(False)
    recent_deep = z.rolling(12, min_periods=6).min().shift(1).lt(-2).fillna(False)
    first = mask & ~recent_deep                     # bar đầu đợt stretch
    later = mask & recent_deep
    return vwap, dev, first, later


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]
    vwap, dev, first, later = build(sol)

    # ===== (1) measure-only: excess@4h theo vị trí episode =====
    fwd4 = sol["close"].shift(-48) / sol["close"] - 1
    for label, m in (("full_mask", first | later), ("first_bar", first), ("later_bars", later)):
        tr_m = m & (sol.index >= T_START) & (sol.index <= T_END)
        idx = sol.index[tr_m]
        ev = fwd4.loc[idx].dropna()
        base = float(fwd4[(sol.index >= T_START) & (sol.index <= T_END)].dropna().mean())
        ex = float(ev.mean() - base) if len(ev) else float("nan")
        logger.info(f"MEASURE {label}: n={len(ev)} ex@4h={ex*100:+.3f}%")

    # ===== (2) implementation — chỉ chạy khi bar đầu có excess dương (rule pre-registered) =====
    tr_ft = first & (sol.index >= T_START) & (sol.index <= T_END)
    ev_first = fwd4.loc[sol.index[tr_ft]].dropna()
    base_tr = float(fwd4[(sol.index >= T_START) & (sol.index <= T_END)].dropna().mean())
    ex_first = float(ev_first.mean() - base_tr) if len(ev_first) else float("nan")
    if not (ex_first == ex_first and ex_first > 0):
        logger.info(f"H12 impl: SKIP — bar đầu không có excess@4h dương ({ex_first:.4f}) "
                    f"→ drift episodic như H9, không tradeable → dừng (không tốn hướng OOS).")
        return

    # engine perturbation count per episode: mỗi episode 1 money slot; impl dùng mask first
    mm = events.mfe_mae(sol["close"], sol["high"], sol["low"], HOLDING)
    funding = FundingSchedule.load()
    # pre-register (idempotent)
    hl.register(hid=HID_IMPL,
                name="H12 implementation: z(vwap-stretch) ≤ −2 ở BAR ĐẦU đợt (z>−2 trong 1h "
                     "trước) → long 4h, partial-BE, SL thiên tai \|MAE q05\|, maker/maker governed",
                source=f"H12 PASS event-study (t=7.58 @1h, +0.568% @4h, VAL +0.370%); "
                       f"measure-only first-bar ex@4h={ex_first:.4f} dương → tradeable candidate",
                criteria={"gate": "settings.gates trên TRAIN", "val": "expectancy cùng dấu"},
                segment="WAVE3_2020-10_2025-08")

    report: dict = {"hid": HID_IMPL, "holding": HOLDING, "first_bar_ex_4h": ex_first,
                    "segments": {}}
    sl_dis = None
    partial_pct = None
    for seg, s0, s1 in (("TRAIN", T_START, T_END), ("VAL", V_START, V_END)):
        seg_mask = (sol.index >= s0) & (sol.index <= s1)
        ev_idx = sol.index[first & seg_mask]
        if seg == "TRAIN":
            sl_dis = float(abs(mm.loc[ev_idx, "mae"].dropna().quantile(0.05)))
            partial_pct = float(mm.loc[ev_idx, "mfe"].dropna().median())
        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": HID_IMPL, "direction": 1,
            "entry_price": sol.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        seg_out: dict = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis,
                         "partial_pct": partial_pct, "runs": {}}
        logger.info(f"=== {seg}: {len(ev_idx)} events (first-bar) | SL {sl_dis:.4f} "
                    f"partial {partial_pct:.4f} ===")
        for entry in ("maker_base", "taker_worst"):
            res = run_backtest(sol.loc[seg_mask, ["open", "high", "low", "close"]], sig,
                               load_cost_model(), scenario=entry, bound="sl_first",
                               activity=None, funding=funding, equity_start=50.0,
                               sizing="governed", risk_cap_pct=3.0, lev_cap_eff=1.0,
                               exit_maker=True, exit_patience=12,
                               partial_be=True, partial_pct=partial_pct)
            m = compute_metrics(res.trades)
            g = gates_check(m) if m.get("n_trades", 0) else {"no_trades": {"ok": False}}
            seg_out["runs"][entry] = {"metrics": m, "gates": g, "engine_stats": res.stats}
            logger.info(f"{seg}/{entry}: n={m.get('n_trades', 0)} "
                        f"expR={m.get('expectancy_r', float('nan')):.4f} "
                        f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} "
                        f"PF={m.get('profit_factor_net', float('nan'))} "
                        f"SQN={m.get('sqn_r', float('nan'))} "
                        f"partialFill={res.stats.get('partial_fill_rate')} "
                        f"ALL_PASS={g.get('ALL_PASS', {}).get('ok')}")
            logger.info(f"    exits={m.get('exit_reasons')} tpY={m.get('trades_per_year', 0):.0f}")
        report["segments"][seg] = seg_out

    tr_ok = report["segments"]["TRAIN"]["runs"]["maker_base"]["gates"].get("ALL_PASS", {}).get("ok")
    tr_tk = report["segments"]["TRAIN"]["runs"]["taker_worst"]["gates"].get("ALL_PASS", {}).get("ok")
    val_exp = report["segments"]["VAL"]["runs"]["maker_base"]["metrics"].get("expectancy_r")
    verdict = "pass" if ((tr_ok or tr_tk) and val_exp is not None and val_exp > 0) else "kill"
    hl.record_verdict(HID_IMPL, verdict, {
        "train_all_pass_maker": tr_ok, "train_all_pass_taker": tr_tk,
        "val_expectancy_r_maker": val_exp,
        "first_bar_ex_4h": ex_first, "sl_disaster_pct": sl_dis, "partial_pct": partial_pct,
    })
    report["verdict"] = verdict
    out = DATA_DIR / "reports" / "w6_h12_impl.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"VERDICT: {verdict} → {out}")


if __name__ == "__main__":
    main()
