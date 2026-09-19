"""M0 mục 6: JIT warm-up + benchmark numba vs rust trên 1 grid cố định → chốt engine.

Chạy: .venv/Scripts/python.exe scripts/benchmark_engine.py
Kết quả: in bảng so sánh + lưu config/vbt_settings.json (settings dùng chung cho dự án).
Grid cố định (synthetic, cùng seed) — so sánh công bằng giữa 2 engine.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import vectorbt as vbt

ROOT = Path(__file__).resolve().parents[1]

# Grid cố định: 600k bar x 16 combo — đại diện 630k nến M5 x grid nhỏ
N_BARS, N_COLS = 600_000, 16
rng = np.random.default_rng(42)
steps = rng.normal(0, 0.001, (N_BARS, N_COLS))
close = pd.DataFrame(100 * np.exp(np.cumsum(steps, axis=0)))
entries = pd.DataFrame(rng.random((N_BARS, N_COLS)) < 0.01)
exits = pd.DataFrame(rng.random((N_BARS, N_COLS)) < 0.01)


def run(engine: str | None) -> float:
    kw = {"engine": engine} if engine else {}
    t0 = time.perf_counter()
    pf = vbt.Portfolio.from_signals(close, entries, exits, freq="5min", **kw)
    _ = pf.total_return()
    return time.perf_counter() - t0


def main() -> None:
    # JIT warm-up (trả phí 1 lần ở setup)
    t0 = time.perf_counter()
    _ = vbt.Portfolio.from_signals(close.iloc[:1000], entries.iloc[:1000], exits.iloc[:1000], freq="5min")
    warmup = time.perf_counter() - t0
    print(f"JIT warm-up: {warmup:.1f}s")

    t_numba = run(None)
    t_rust = run("rust")
    print(f"numba : {t_numba:6.2f}s  ({N_BARS:,} bars x {N_COLS} combo)")
    print(f"rust  : {t_rust:6.2f}s")

    winner = "rust" if t_rust < t_numba else "numba"
    vbt.settings["engine"] = winner
    vbt.settings["caching"]["enabled"] = True
    (ROOT / "config").mkdir(exist_ok=True)
    vbt.settings.save(str(ROOT / "config" / "vbt_settings.json"))
    print(f"Chốt engine: {winner} → config/vbt_settings.json")


if __name__ == "__main__":
    main()
