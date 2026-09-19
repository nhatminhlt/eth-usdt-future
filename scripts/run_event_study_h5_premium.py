"""WAVE 2 — H5 premium/basis basis (nguồn thông tin MỚI, chưa từng test): premiumIndexKlines
REST fapi/v1/premiumIndexKlines (vision 404 — claim cũ plan sai, probe lại bắt được).

Premium = mark − index (fraction). Premium cực cao = longs chen chúc (trả funding đắt) →
crowding → drift XUỐNG?; cực thấp/âm = shorts chen chúc → drift LÊN? Literature: crowding/
basis extremes → reversal (plan M2.6 H5). Test CẢ HAI hướng pre-registered.

Segment ledger mới "WAVE2_2020-10_2023-06" — căn cứ: nguồn thông tin MỚI (premium basis,
không suy ra được từ price/volume/OI/funding đã dùng); DSR cuối cùng phải ĐẾM HẾT rows
ledger-wide (38 + Wave 2) — kỷ luật multiple-testing giữ nguyên ở tầng DSR.

Criteria pre-registered (giống M2.5 mặc định): excess ≥ 0.05% @+1h, t ≥ 2, CI95 > 0 trên
TRAIN 2020-10→2023-06; VAL 2023-07→2024-06 giữ hướng.

Chạy: .venv/Scripts/python.exe scripts/run_event_study_h5_premium.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.binance_client import BinanceFuturesPublic
from solfut.data.downloader import DATA_DIR
from solfut.research import events, hypotheses as hl

T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}
HORIZONS = {"+5m": 1, "+15m": 3, "+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}


def download_premium(symbol: str, interval: str = "5m") -> pd.DataFrame:
    out = DATA_DIR / "premium" / f"{symbol}_premium_{interval}.parquet"
    if out.exists():
        return pd.read_parquet(out)
    client = BinanceFuturesPublic()
    rows = []
    cursor = int(T_START.timestamp() * 1000)
    end_ms = int((V_END + pd.Timedelta(days=2)).timestamp() * 1000)
    while cursor < end_ms:
        batch = client._get(f"/fapi/v1/premiumIndexKlines",
                            {"symbol": symbol, "interval": interval,
                             "startTime": cursor, "limit": 1500})
        if not batch:
            break
        rows.extend(batch)
        last_close = batch[-1][6]
        cursor = last_close + 1
        time.sleep(0.15)                    # pacing weight
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close",
                                     "ignore1", "close_time", "ignore2", "n",
                                     "ignore3", "ignore4", "ignore5"])
    df = df[["open_time", "open", "high", "low", "close"]].apply(pd.to_numeric)
    df["premium"] = df["close"].replace(0, np.nan)      # all-zero row = thiếu dữ liệu 2020
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    df[["premium"]].to_parquet(out)
    logger.info(f"{symbol} premium: {len(df)} bars → {out.name}")
    return df[["premium"]]


def main() -> None:
    prem = download_premium("SOLUSDT")
    sol = pd.read_parquet(DATA_DIR / "SOLUSDT_5m_enriched.parquet").sort_index()
    sol = sol[sol.index <= V_END + pd.Timedelta(days=2)]
    p = prem["premium"].reindex(sol.index)
    p_rank = p.rolling(8640, min_periods=2880).rank(pct=True)

    train_idx = sol.index[(sol.index >= T_START) & (sol.index <= T_END)]
    base_mask_all = sol.index <= V_END

    hids = {
        "H5a_premium_extreme_high_short": (p_rank > 0.95, -1),
        "H5b_premium_extreme_low_long": (p_rank < 0.05, +1),
    }
    seg = "WAVE2_2020-10_2023-06"
    report: dict = {"segment": seg, "info": "nguồn thông tin mới: premium basis (REST premiumIndexKlines)"}
    for hid, (mask, sign) in hids.items():
        hl.register(hid=hid,
                    name=f"{hid}: premium rank 30d {'>p95 → drift xuống (short)' if sign < 0 else '<p5 → drift lên (long)'}",
                    source="PLAN M2.6 H5 crowding/basis reversal; data REST premiumIndexKlines",
                    criteria=dict(CRITERIA), segment=seg)
        ev = mask & (sol.index >= T_START) & (sol.index <= T_END)
        res = events.run_event_study(sol, ev, hid, horizons=HORIZONS, sign=sign)
        ex1 = res.excess_by_horizon.get("+1h")
        t1 = res.t_by_horizon.get("+1h")
        ci1 = res.ci_event_by_horizon.get("+1h", {})
        lo1 = ci1.get("lo")
        ok = bool(ex1 == ex1 and ex1 >= 0.0005 and t1 == t1 and t1 >= 2.0
                  and lo1 == lo1 and lo1 is not None and lo1 > 0)
        # VAL giữ hướng
        fwd = sol["close"].shift(-12) / sol["close"] - 1
        ev_val = mask & (sol.index > T_END) & (sol.index <= V_END)
        ev_val_fwd = (sign * fwd).loc[sol.index[ev_val]].dropna()
        base_val = float((sign * fwd)[base_mask_all & (sol.index > T_END) & (sol.index <= V_END)].dropna().mean())
        val_ex = float(ev_val_fwd.mean() - base_val) if len(ev_val_fwd) >= 100 else float("nan")
        val_ok = bool(val_ex == val_ex and val_ex > 0)
        verdict = "pass" if (ok and val_ok) else ("kill" if not ok else "kill_val")
        result = {
            "n_events": int(res.n_events), "sign": sign,
            "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
            "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
            "ci95_1h": [ci1.get("lo"), ci1.get("hi")],
            "val_excess_1h": val_ex, "val_keep_direction": val_ok,
        }
        hl.record_verdict(hid, "pass" if verdict == "pass" else "kill", result)
        report[hid] = {"verdict": verdict, "result": result}
        logger.info(f"{hid}: n={res.n_events} ex@1h={ex1*100 if ex1==ex1 else float('nan'):+.3f}% "
                    f"t@1h={t1} ex@4h={res.excess_by_horizon.get('+4h', 0)*100:+.3f}% "
                    f"val={val_ex*100:+.3f}% → {verdict}")

    out = DATA_DIR / "reports" / "m2_6_h5_premium.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
