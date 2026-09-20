"""Cross-symbol replication (M2.5 extension): test lại ĐÚNG định nghĩa 2 giả thuyết fade ĐÃ PASS
trên SOL (H2b seesaw, H4a2 sell-surge reversal) trên 3 perp khác — ETHUSDT, DOGEUSDT, AVAXUSDT.

Lý do phương pháp luận: ledger TRAIN của SOL đầy 30/30 (kỷ luật chống xoay bánh). Symbol MỚI =
dữ liệu MỚI → segment ledger riêng theo symbol ("TRAIN_2020-10_2023-06_<SYM>"), tiêu chí
PRE-REGISTERED GIỐNG HỆT bản gốc (excess ≥ 0.05% @+1h, t ≥ 2, CI > 0 — events.judge).
Câu hỏi: drift fade là hiện tượng vi cấu trúc phổ biến (→ portfolio cross-symbol) hay artifact
riêng SOL (→ NO-GO trung thực)?

H4d (OI squeeze) bỏ qua đợt này — cần tải metrics OI theo symbol (nặng); nếu H2b/H4a2 replicate
mới mở rộng. ATR-tier (atrPct>70) chỉ làm attribution context, không claim.

Chạy: .venv/Scripts/python.exe scripts/run_cross_symbol_replication.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
from loguru import logger

from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events, hypotheses as hl
from solfut.research.splits import split_mask

SYMBOLS = ["BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]   # W3 universe expansion (đợt 2)
T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
CRITERIA = {"excess_min_pct": 0.0005, "t_min": 2.0, "horizon": "+1h"}   # giống hệt bản SOL gốc
HORIZONS = {"+5m": 1, "+15m": 3, "+1h": 12, "+4h": 48, "+8h": 96, "+24h": 288}


def load_5m(symbol: str) -> pd.DataFrame:
    df = load_monthlies(symbol, "5m")
    df = df[["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"]]
    for c in ("open", "high", "low", "close", "volume", "taker_buy_volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.sort_index()


def btc_jump_down(index: pd.DatetimeIndex) -> pd.Series:
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    ret = btc["close"].pct_change()
    sigma = ret.rolling(96).std()
    return (ret <= -2 * sigma).reindex(index).fillna(False)


def sell_surge_z(sol: pd.DataFrame) -> pd.Series:
    signed = 2 * sol["taker_buy_volume"] - sol["volume"]
    imb = signed.rolling(12).sum() / sol["volume"].rolling(12).sum().replace(0, np.nan)
    return ((imb - imb.rolling(288).mean()) / imb.rolling(288).std())


def atr_pct(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    return atr.rolling(8640, min_periods=2880).rank(pct=True)


def main() -> None:
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    report: dict = {}
    for sym in SYMBOLS:
        try:
            df = load_5m(sym)
        except FileNotFoundError:
            logger.warning(f"{sym}: chưa tải đủ — bỏ qua")
            continue
        seg = f"TRAIN_2020-10_2023-06_{sym}"
        df = df[df.index <= T_END + pd.Timedelta(days=2)]
        logger.info(f"===== {sym}: {df.index[0]} → {df.index[-1]} ({len(df)} bars) =====")

        masks = {
            f"H2b_seesaw_long_{sym}": btc_jump_down(df.index),
            f"H4a2_sell_surge_reversal_long_{sym}": (sell_surge_z(df) <= -2).fillna(False),
        }
        sym_out: dict = {"span": [str(df.index[0]), str(df.index[-1])], "hypotheses": {}}
        atrp = atr_pct(df)
        for hid, mask in masks.items():
            # PRE-REGISTER trước khi đo (criteria giống hệt bản SOL gốc)
            hl.register(hid=hid,
                        name=f"{hid} — replication trên {sym}, định nghĩa GIỐNG HỆT bản SOL",
                        source=f"Replication của hid bản SOL (H2b/H4a2 PASS trên SOLUSDT)",
                        criteria=dict(CRITERIA), segment=seg)

            ev_idx = df.index[mask & (df.index >= T_START) & (df.index <= T_END)]
            res = events.run_event_study(df, mask, hid, horizons=HORIZONS)
            train_mask = (df.index >= T_START) & (df.index <= T_END)
            # chấm theo criteria @+1h — logic tương đương events.judge("TRAIN", ...)
            ex1 = res.excess_by_horizon.get("+1h")
            t1 = res.t_by_horizon.get("+1h")
            ci1 = res.ci_event_by_horizon.get("+1h", {})
            lo1 = ci1.get("lo")
            ok = bool(ex1 == ex1 and ex1 >= CRITERIA["excess_min_pct"]
                      and t1 == t1 and t1 >= CRITERIA["t_min"]
                      and lo1 == lo1 and lo1 is not None and lo1 > 0)
            verdict = "pass" if ok else "kill"

            # attribution context: high-vol tier @+4h (không claim)
            fwd4 = df["close"].shift(-48) / df["close"] - 1
            base4 = float(fwd4[train_mask].dropna().mean())
            ev_hi = fwd4.loc[ev_idx][atrp.loc[ev_idx] > 0.7].dropna()
            hi_ex = float((ev_hi.mean() - base4) * 100) if len(ev_hi) >= 100 else None

            result = {
                "n_events": int(len(ev_idx)),
                "excess_by_horizon": {k: float(v) for k, v in res.excess_by_horizon.items()},
                "t_by_horizon": {k: float(v) for k, v in res.t_by_horizon.items()},
                "ci95_1h": [ci1.get("lo"), ci1.get("hi")],
                "atr_hi_excess_4h_pct": hi_ex,
                "n_atr_hi_4h": int(len(ev_hi)),
            }
            sym_out["hypotheses"][hid] = {"verdict": verdict, "result": result}
            hl.record_verdict(hid, verdict, result)
            logger.info(f"{hid}: n={len(ev_idx)} ex@1h={ex1*100 if ex1==ex1 else float('nan'):+.3f}% "
                        f"t@1h={t1} ex@4h={res.excess_by_horizon.get('+4h', 0)*100:+.3f}% "
                        f"ex@24h={res.excess_by_horizon.get('+24h', 0)*100:+.3f}% "
                        f"atrHi@4h={hi_ex} → {verdict}")
        report[sym] = sym_out

    out = DATA_DIR / "reports" / "cross_symbol_replication.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
