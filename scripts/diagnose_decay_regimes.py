"""Diagnostic attribution (KHÔNG tốn ledger — thuần phân tầng các giả thuyết ĐÃ PASS, mục 4b
"Edge đo theo regime từ khâu event-study"): decay curve tới 24h + drift theo regime con.

Câu hỏi M4 để lại: H2b có drift +0.335% @4h (2.6× RT taker) nhưng M3 đặt holding 12 bar.
Hỏi: (1) drift phát triển thế nào tới 24h? (2) regime con nào TẬP TRUNG drift — funding sign,
ATR percentile, BTC D1 trend, giờ UTC, taker imbalance? Chỉ đo trên TRAIN — không đụng VAL/OOS.

Chạy: .venv/Scripts/python.exe scripts/diagnose_decay_regimes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR
from solfut.features.context import btc_d1_trend, sol_regime
from solfut.features.orderflow import add_oi_context, load_oi
from solfut.research.splits import split_mask
from solfut.strategies.hypothesis_fades import generate_signals

HORIZONS = {"+1h": 12, "+2h": 24, "+4h": 48, "+8h": 96, "+12h": 144, "+24h": 288}


def main() -> None:
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sig = generate_signals(sol)

    # baseline vô điều kiện theo horizon (TRAIN)
    train = split_mask(sol.index, "TRAIN")
    fwd = {name: sol["close"].shift(-h) / sol["close"] - 1 for name, h in HORIZONS.items()}

    # context dữ liệu
    sol_d1 = pd.read_parquet(DATA_DIR / "SOLUSDT_1d.parquet")
    sol_d1.index = pd.to_datetime(sol_d1["open_time"], unit="ms", utc=True)
    btc_d1 = pd.read_parquet(DATA_DIR / "BTCUSDT_1d.parquet")
    btc_d1.index = pd.to_datetime(btc_d1["open_time"], unit="ms", utc=True)
    reg = sol_regime(sol_d1)["regime"]
    btrend = btc_d1_trend(btc_d1)["btc_trend"]

    # funding sign tại event (mark gần nhất TRƯỚC event — không lookahead)
    fdf = pd.read_parquet(DATA_DIR / "funding" / "SOLUSDT_funding.parquet")
    fdf["ts"] = pd.to_datetime(fdf["fundingTime"], utc=True, unit="ms")
    fr = fdf.set_index("ts")["fundingRate"].astype(float).sort_index()
    # ATR percentile (30 ngày rolling percentile của atr14 5m)
    atr_pct = sol["atr14"].rolling(8640).rank(pct=True)

    for sid, grp in sig.groupby("sid"):
        ev = grp[split_mask(pd.DatetimeIndex(grp["entry_time"]), "TRAIN").values]
        ev_idx = pd.DatetimeIndex(ev["entry_time"])
        logger.info(f"===== {sid}: {len(ev)} events TRAIN =====")
        rows = []
        for hname, h in HORIZONS.items():
            ev_fwd = fwd[hname].loc[ev_idx].dropna()
            base = fwd[hname][train].dropna().mean()
            rows.append({"horizon": hname, "n": len(ev_fwd),
                         "mean_pct": float(ev_fwd.mean() * 100),
                         "excess_pct": float((ev_fwd.mean() - base) * 100),
                         "t": float((ev_fwd.mean() - base) / (ev_fwd.std(ddof=1) / np.sqrt(len(ev_fwd))))})
        logger.info(f"decay: {pd.DataFrame(rows).to_string(index=False)}")

        # phân tầng tại horizon mạnh nhất của decay (in đầy đủ mọi horizon)
        for hname in ("+4h", "+8h", "+12h", "+24h"):
            ev_fwd = fwd[hname].loc[ev_idx]
            base = fwd[hname][train].dropna().mean()
            d = pd.DataFrame({
                "fwd": ev_fwd,
                "funding_pos": pd.Series(fr.reindex(ev_idx, method="ffill").values, index=ev_idx) > 0,
                "atr_pct_hi": pd.Series(atr_pct.loc[ev_idx].values, index=ev_idx) > 0.7,
                "btc_trend": pd.Series(btrend.reindex(ev_idx.floor("D")).values, index=ev_idx),
                "regime": pd.Series(reg.reindex(ev_idx.floor("D")).values, index=ev_idx),
                "hour": ev_idx.hour,
                "imb_pos": pd.Series(sol["taker_imbalance_1h"].loc[ev_idx].values, index=ev_idx) > 0,
            })
            d = d.dropna(subset=["fwd"])
            parts = [f"h={hname} excess_all={float((d['fwd'].mean() - base) * 100):+.3f}%"]
            for cond, label in [
                (d["funding_pos"], "funding_pos"), (~d["funding_pos"], "funding_neg"),
                (d["atr_pct_hi"], "atrPct>70"), (~d["atr_pct_hi"], "atrPct<=70"),
                (d["btc_trend"] == "down", "btcTrend=down"), (d["btc_trend"] == "up", "btcTrend=up"),
                (d["regime"] == "bear", "regime=bear"), (d["regime"] == "bull", "regime=bull"),
                (d["regime"] == "chop", "regime=chop"),
                (d["hour"].between(12, 21), "hour12-21"), (~d["hour"].between(12, 21), "hourOutside"),
                (d["imb_pos"], "imb1h+"), (~d["imb_pos"], "imb1h-"),
            ]:
                sub = d[cond]["fwd"]
                if len(sub) >= 100:
                    ex = (sub.mean() - base) * 100
                    t = (sub.mean() - base) / (sub.std(ddof=1) / np.sqrt(len(sub)))
                    parts.append(f"{label}: n={len(sub)} ex={ex:+.3f}% t={t:+.1f}")
            logger.info(" | ".join(parts))


if __name__ == "__main__":
    main()
