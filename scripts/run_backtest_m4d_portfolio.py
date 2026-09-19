"""M4d — PORTFOLIO BACKTEST H2b high-vol tier 4 symbol (pre-registered TRƯỚC KHI CHẠY).

Nền tảng bằng chứng:
- H2b BTC-seesaw PASS trên 4/4 symbol (SOL t=6.7; ETH t=3.3; DOGE t=3.7; AVAX t=7.7 @+1h,
  cùng định nghĩa, cùng window — cross_symbol_replication.json).
- Tier high-vol (atrPct 30d > 0.70) lift drift @4h trên MỌI symbol (SOL 2.7×, ETH 2.2×,
  DOGE 3.1×, AVAX 2.6×) — mechanism nhất quán: seesaw bounce cần regime vol cao.

Cấu hình pre-registered (KHÔNG chỉnh sau khi thấy kết quả):
- Trigger: BTC 5m ret ≤ −2σ(96 bar) — giống hệt H2b gốc.
- Filter: atrPct>0.70 của symbol tại event bar.
- Entry: close event bar (taker) / post-only tại low event bar (maker, fill trade-through).
- Holding 48 bar (4h) — decay curve; TP KHÔNG (horizon exit — M4b chứng minh bracket rò).
- SL thiên tai = |MAE q05| 48-bar của TRAIN events CỦA CHÍNH SYMBOL đó (derive, không grid).
- Flat cuối ngày UTC (luật plan); KHÔNG activity mask cho lớp 4h (evidence M4c: cắt 56%
  events, drift trong/ngoài window tương đương — diagnostic ghi ledger A2).
- Funding thật từng symbol khi băng qua mốc settle.
- Sizing: 2 chế độ pre-registered, báo cáo CẢ HAI:
    (a) percent_risk 1%/lệnh — convention plan;
    (b) governed: notional = max(minNotional, min(equity×1×, equity×3%/sl)) — lớp wide-stop
        (M4c: percent-risk + SL 9.47% → notional 5.3 chạm sàn 5 USDT + R-dilution 10×);
        risk_cap 3% (ETH minNotional 20 USDT → worst-case 20×~7% ≈ 1.4 = 2.8% equity).
- Mỗi symbol một "pocket" equity $50 độc lập (không cross-compound — xấp xỉ ghi rõ).
- Portfolio = hợp trades 4 symbol; gates áp trên portfolio aggregate.

Verdict: portfolio ALL_PASS (settings.gates) → pass; VAL confirm cùng cấu hình sau.

Chạy: .venv/Scripts/python.exe scripts/run_backtest_m4d_portfolio.py
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
from solfut.backtest.monte_carlo import mc_drawdown
from solfut.backtest.random_baseline import edge_vs_random, random_baseline
from solfut.data.downloader import DATA_DIR, load_monthlies
from solfut.research import events
from solfut.research import hypotheses as hl

SYMBOLS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "AVAXUSDT"]
HOLDING = 48
T_START = pd.Timestamp("2020-10-01", tz="UTC")
T_END = pd.Timestamp("2023-06-30 23:59", tz="UTC")
V_START = pd.Timestamp("2023-07-01", tz="UTC")
V_END = pd.Timestamp("2024-06-30 23:59", tz="UTC")
RISK_CAP_PCT = 3.0
LEV_EFF = 1.0


def load_5m(symbol: str) -> pd.DataFrame:
    df = load_monthlies(symbol, "5m")
    df = df[["open_time", "open", "high", "low", "close", "volume", "taker_buy_volume"]].copy()
    for c in ("open", "high", "low", "close", "volume", "taker_buy_volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.sort_index()


def btc_jump_mask(index: pd.DatetimeIndex) -> pd.Series:
    btc = pd.read_parquet(DATA_DIR / "BTCUSDT_5m.parquet")
    btc.index = pd.to_datetime(btc["open_time"], unit="ms", utc=True)
    ret = btc["close"].pct_change()
    sigma = ret.rolling(96).std()
    return (ret <= -2 * sigma).reindex(index).fillna(False)


def atr_pct(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean().rolling(8640, min_periods=2880).rank(pct=True)


def run_segment(sol_specs: dict, contract_by_sym: dict, seg: str, s0: pd.Timestamp,
                s1: pd.Timestamp, sizing: str) -> dict:
    out: dict = {"symbols": {}, "sizing": sizing, "segment": seg}
    all_trades = []
    for sym in SYMBOLS:
        try:
            df = load_5m(sym)
        except FileNotFoundError:
            logger.warning(f"{sym}: thiếu dữ liệu — bỏ qua")
            continue
        # atrPct tính trên FULL history TRƯỚC khi cắt segment (tránh rolling lạnh ở đầu VAL)
        atrp = atr_pct(df)
        df = df[(df.index >= s0) & (df.index <= s1 + pd.Timedelta(days=2))]
        atrp = atrp.loc[df.index]
        mask = btc_jump_mask(df.index) & atrp.gt(0.70).fillna(False)
        ev_idx = df.index[mask & (df.index >= s0) & (df.index <= s1)]

        # SL thiên tai |MAE q05| — derive TRÊN TRAIN của chính symbol (VAL dùng lại số TRAIN)
        mm = events.mfe_mae(df["close"], df["high"], df["low"], HOLDING)
        if seg.startswith("TRAIN"):
            sl_dis = float(abs(mm.loc[ev_idx, "mae"].dropna().quantile(0.05)))
        else:
            sl_dis = sol_specs.setdefault(sym, {}).get("sl_disaster")
        if not sl_dis:
            logger.warning(f"{sym}: không derive được SL — bỏ qua")
            continue
        sol_specs.setdefault(sym, {})["sl_disaster"] = sl_dis

        sig = pd.DataFrame({
            "entry_time": ev_idx, "sid": f"H2bHV_{sym}", "direction": 1,
            "entry_price": df.loc[ev_idx, "close"].values,
            "sl_pct": sl_dis, "tp_pct": np.nan, "holding_bars": HOLDING,
        })
        funding = FundingSchedule.load(sym)
        res = run_backtest(df, sig, load_cost_model(), scenario="taker_worst",
                           bound="sl_first", activity=None, funding=funding,
                           equity_start=50.0, sizing=sizing, risk_cap_pct=RISK_CAP_PCT,
                           lev_cap_eff=LEV_EFF, contract=contract_by_sym[sym])
        m = compute_metrics(res.trades)
        out["symbols"][sym] = {"n_events": int(len(ev_idx)), "sl_disaster_pct": sl_dis,
                               "metrics": m, "engine_stats": res.stats}
        if len(res.trades):
            all_trades.append(res.trades.assign(symbol=sym))
        logger.info(f"[{seg}/{sizing}] {sym}: n={m.get('n_trades', 0)} expR={m.get('expectancy_r', float('nan')):.4f} "
                    f"grossR={m.get('gross_expectancy_r', float('nan')):.4f} PF={m.get('profit_factor_net', float('nan'))} "
                    f"sl={sl_dis:.3f} skips_size={res.stats['n_skip_size']}")

    if not all_trades:
        out["portfolio"] = {"n_trades": 0}
        return out
    tr = pd.concat(all_trades, ignore_index=True).sort_values("exit_time")
    eq = 4 * 50.0 + tr["net_pnl"].cumsum()                       # 4 pocket × $50
    peak = np.maximum.accumulate(np.concatenate([[4 * 50.0], eq.values]))[1:]
    dd = float(((peak - eq.values) / peak * 100).max())
    r = tr["r_net"].to_numpy(float)
    lo, hi = bootstrap_expectancy_ci(r)
    pm = {
        "n_trades": int(len(tr)), "expectancy_r": float(np.nanmean(r)),
        "gross_expectancy_r": float(np.nanmean(tr["r_gross"])),
        "profit_factor_net": float(tr.loc[tr["net_pnl"] > 0, "net_pnl"].sum()
                                   / abs(tr.loc[tr["net_pnl"] <= 0, "net_pnl"].sum()))
        if (tr["net_pnl"] <= 0).any() else float("inf"),
        "sqn_r": float(np.sqrt(len(r)) * np.nanmean(r) / np.nanstd(r, ddof=1)),
        "max_dd_pct": dd, "equity_end": float(eq.iloc[-1]),
        "expectancy_ci95": [lo, hi],
        "trades_per_year": float(len(tr) / max((tr["exit_time"].max() - tr["exit_time"].min()).days / 365.25, 1e-9)),
        "win_rate": float((tr["net_pnl"] > 0).mean()),
        "total_net_usdt": float(tr["net_pnl"].sum()),
        "exit_reasons": tr["exit_reason"].value_counts().to_dict(),
    }
    pm["gates"] = gates_check(pm)
    out["portfolio"] = {"metrics": pm}
    logger.info(f"[{seg}/{sizing}] PORTFOLIO: n={pm['n_trades']} expR={pm['expectancy_r']:.4f} "
                f"CI=[{lo:.4f},{hi:.4f}] PF={pm['profit_factor_net']:.2f} SQN={pm['sqn_r']:.2f} "
                f"DD={dd:.1f}% net={pm['total_net_usdt']:.2f} USDT ALL_PASS={pm['gates']['ALL_PASS']['ok']}")
    return out


def main() -> None:
    specs_raw = json.loads((DATA_DIR / "reports" / "symbol_specs.json").read_text(encoding="utf-8"))
    contract_by_sym = {s: {"lot_step": v["step_size"], "min_qty": v["min_qty"],
                           "min_notional": v["min_notional"], "leverage_cap": 5}
                       for s, v in specs_raw.items() if not s.startswith("_")}

    report: dict = {"config": {"holding": HOLDING, "risk_cap_pct": RISK_CAP_PCT, "lev_eff": LEV_EFF,
                               "symbols": SYMBOLS}, "train": {}, "val": {}}
    # ledger: 4 implementation rows (1/symbol segment) — đăng ký TRƯỚC KHI CHẠY
    impl_ids = {}
    for sym in SYMBOLS:
        hid = f"H2bHV_impl_{sym}"
        impl_ids[sym] = hid
        hl.register(hid=hid,
                    name=f"{hid}: portfolio implementation của H2b high-vol tier 4h "
                         f"(horizon exit, SL thiên tai |MAE q05| TRAIN, governed sizing cap 3%)",
                    source="H2b PASS trên symbol + tier lift cross-symbol (replication report)",
                    criteria={"gate": "settings.gates trên TRAIN (portfolio + per-symbol)",
                              "val": "portfolio expectancy cùng dấu và per-symbol không sụp"},
                    segment=f"TRAIN_2020-10_2023-06_{sym}")

    state: dict = {}
    for sizing in ("percent_risk", "governed"):
        state[sizing] = {}
        report["train"][sizing] = run_segment(state[sizing], contract_by_sym, "TRAIN",
                                              T_START, T_END, sizing)
    # VAL — dùng SL đã derive từ TRAIN
    for sizing in ("percent_risk", "governed"):
        report["val"][sizing] = run_segment(state[sizing], contract_by_sym, "VAL",
                                            V_START, V_END, sizing)

    # verdict per symbol trên governed (chế độ lớp-wide-stop) + portfolio
    for sym in SYMBOLS:
        tr_best = report["train"]["governed"]["symbols"].get(sym, {})
        g = (tr_best.get("metrics") or {}).get("n_trades", 0) and gates_check(tr_best["metrics"])
        ok = bool(g and g.get("ALL_PASS", {}).get("ok"))
        val_sym = report["val"]["governed"]["symbols"].get(sym, {})
        val_ok = (val_sym.get("metrics") or {}).get("expectancy_r")
        val_ok = None if val_sym.get("n_events", 0) == 0 else bool(val_ok is not None and val_ok > 0)
        hl.record_verdict(impl_ids[sym], "pass" if ok and val_ok is not False else "kill", {
            "train": {"n_trades": tr_best.get("metrics", {}).get("n_trades"),
                      "expectancy_r": tr_best.get("metrics", {}).get("expectancy_r"),
                      "all_pass": ok},
            "val_expectancy_r": val_sym.get("metrics", {}).get("expectancy_r"),
            "val_keep_direction": val_ok,
            "sl_disaster_pct": state["governed"].get(sym, {}).get("sl_disaster"),
        })

    out = DATA_DIR / "reports" / "m4d_portfolio.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"→ {out}")


if __name__ == "__main__":
    main()
