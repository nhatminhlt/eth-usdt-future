"""Quality gate cho klines — pattern quality-gate/quarantine của V1.

Trả về df sạch + report; nến lỗi bị tách ra data/quarantine/ để kiểm tra tay, không âm thầm xoá.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def check_klines(df: pd.DataFrame, interval_minutes: int, name: str = "klines") -> tuple[pd.DataFrame, dict]:
    report: dict = {"name": name, "rows_in": len(df)}
    bad_masks = []

    # OHLC violation
    ohlc_bad = (
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df["high"] < df["low"])
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    )
    bad_masks.append(ohlc_bad)
    report["ohlc_violations"] = int(ohlc_bad.sum())

    # duplicates
    dup = df.duplicated(subset="open_time", keep="first")
    report["duplicates"] = int(dup.sum())

    # gaps (nến bị thiếu — nội suy là cấm; chỉ report, gap lớn phải tra nguồn)
    t = df.sort_values("open_time")["open_time"]
    step = interval_minutes * 60_000
    gaps = t.diff() > step
    report["gaps"] = int(gaps.sum()) - 1 if len(t) else 0  # -1: gap đầu nếu listing
    big_gaps = (t.diff() > step)[lambda s: s]
    if len(big_gaps):
        idx = big_gaps.index[:10]
        report["gap_examples"] = [
            {"after": str(pd.to_datetime(t.loc[i - 1], unit="ms")),
             "before": str(pd.to_datetime(t.loc[i], unit="ms"))}
            for i in idx if i > 0
        ][:5]

    bad = ohlc_bad | dup.reindex(df.index, fill_value=False)
    quarantine = df[bad]
    clean = df[~bad].drop_duplicates(subset="open_time", keep="first").sort_values("open_time").reset_index(drop=True)

    if len(quarantine):
        qdir = DATA_DIR / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        qpath = qdir / f"{name}_quarantine.parquet"
        quarantine.to_parquet(qpath, index=False)
        logger.warning(f"{name}: tách {len(quarantine)} nến lỗi → {qpath.name}")

    report["rows_out"] = len(clean)
    logger.info(f"{name}: {report['rows_in']} → {report['rows_out']} "
                f"(OHLC bad {report['ohlc_violations']}, dup {report['duplicates']}, gaps {report['gaps']})")
    return clean, report


def ohlc_columns_float(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=["ignore"], errors="ignore")
    for c in ("open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_volume", "taker_buy_quote_volume"):
        df[c] = df[c].astype("float64")
    df["count"] = df["count"].astype("int64")
    return df
