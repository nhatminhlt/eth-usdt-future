"""Ba chiến thuật dựng trên 3 giả thuyết PASS+VAL (M3) — fade/mean-reversion long-bias:

- A_seesaw_long  (H2b): BTC 5m rơi ≥ 2σ → long SOL tại đóng bar event
- B_flush_bounce_long (H4a2): taker sell surge z ≤ −2 → long
- C_oi_squeeze_long_4h (H4d): OI↓ + giá↑ (squeeze quadrant) → long, holding 4h

Entry: đóng bar event (taker) hoặc post-only limit ở extreme bar event (maker variant).
SL = |MAE q25|, TP = MFE q75 của event distribution (ledger). Flat trong ngày.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from solfut.features.orderflow import add_oi_context, load_oi
from solfut.strategies.base import StrategySpec

SPECS = [
    StrategySpec(sid="A_seesaw_long", hypothesis_id="H2b_btc_jump_down_seesaw_long",
                 direction=1, holding_bars=12),
    StrategySpec(sid="B_flush_bounce_long", hypothesis_id="H4a2_sell_surge_reversal_long",
                 direction=1, holding_bars=12),
    StrategySpec(sid="C_oi_squeeze_long_4h", hypothesis_id="H4d_oi_squeeze_long_4h",
                 direction=1, holding_bars=48),
]


def _btc_jump_down(sol_index: pd.DatetimeIndex) -> pd.Series:
    btc = pd.read_parquet(__import__("solfut.data.downloader", fromlist=["DATA_DIR"]).DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    ret = btc["close"].pct_change()
    sigma = ret.rolling(96).std()
    return (ret <= -2 * sigma).reindex(sol_index).fillna(False)


def generate_signals(sol_enriched: pd.DataFrame) -> pd.DataFrame:
    """Trả về bảng tín hiệu: entry_time, sid, direction, hypothesis_t, entry_price, sl_pct, tp_pct."""
    sol = sol_enriched.sort_index()
    imb_z = ((sol["taker_imbalance_fast"] - sol["taker_imbalance_fast"].rolling(288).mean())
             / sol["taker_imbalance_fast"].rolling(288).std())

    masks = {
        "A_seesaw_long": _btc_jump_down(sol.index),
        "B_flush_bounce_long": (imb_z <= -2).fillna(False),
        "C_oi_squeeze_long_4h": None,  # điền sau khi có OI
    }
    oi = load_oi()
    sol_oi = add_oi_context(sol[["close"]].copy(), oi)
    in_squeeze = (sol_oi["oi_quadrant"] == "oi_down_price_up")
    # Chỉ vào bar CHUYỂN trạng thái (bar đầu của đợt squeeze) — không vào mỗi bar trong trạng thái
    masks["C_oi_squeeze_long_4h"] = in_squeeze & ~in_squeeze.shift(1, fill_value=False)

    t_map = {"A_seesaw_long": 6.67, "B_flush_bounce_long": 6.08, "C_oi_squeeze_long_4h": 8.03}
    rows = []
    for spec in SPECS:
        mask = masks[spec.sid]
        for ts in sol.index[mask]:
            rows.append({
                "entry_time": ts, "sid": spec.sid, "direction": spec.direction,
                "hypothesis_t": t_map[spec.sid], "entry_price": sol.at[ts, "close"],
                "holding_bars": spec.holding_bars,
            })
    sig = pd.DataFrame(rows)
    return sig


def attach_sl_tp(signals: pd.DataFrame) -> pd.DataFrame:
    """SL/TP từ ledger (derive — không grid mù)."""
    from solfut.strategies.base import derive_sl_tp, load_passing_hypotheses
    passing = load_passing_hypotheses()
    specs = {s.sid: s for s in SPECS}
    out = signals.copy()
    sls, tps, rrs = [], [], []
    for _, row in out.iterrows():
        spec = specs[row["sid"]]
        params = derive_sl_tp(spec, passing[spec.hypothesis_id])
        sls.append(params["sl_pct"])
        tps.append(params["tp_pct"])
        rrs.append(params["rr"])
    out["sl_pct"], out["tp_pct"], out["rr"] = sls, tps, rrs
    return out
