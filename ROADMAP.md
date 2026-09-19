# ROADMAP triển khai solusd-future-v2 — các bước tuần tự từ PLAN.md

> **Ngày tạo:** 2026-09-20. File này là checklist thi công rút ra từ [`.zcode/plans/PLAN.md`](.zcode/plans/PLAN.md) — plan là nguồn sự thật, roadmap chỉ là thứ tự làm + trạng thái. Cập nhật tick ✅ ngay khi hoàn thành từng mục.
>
> **Nguyên tắc xuyên suốt:** mọi luật cứng mục 11 của PLAN.md có hiệu lực từ dòng code đầu tiên; mỗi milestone xong phải commit + push; các con số không hardcode — lấy từ `config/settings.yaml`.

---

## M0 — Môi trường (0.5 ngày)

- [x] 1. `python -m venv .venv` (Python 3.11) + kích hoạt trong mọi phiên làm việc ✅ 2026-09-20
- [x] 2. `pip install pyarrow pyyaml pytest loguru ccxt python-binance` ✅ (kèm pandas/numpy/scipy)
- [x] 3. `pip install -e C:\Project\vectorbt` (repo local v1.1.0) ✅ — phải hạ `plotly<6` (vectorbt 1.1.0 incompatible plotly≥6: scattermapbox renamed); `vectorbt-rust` wheel cài OK
- [x] 4. Smoke test: `import vectorbt as vbt` + `from_signals` chạy ✅
- [x] 5. Verify API: ping + exchangeInfo ✅ (tick 0.01, step/minQty 0.01, minNotional 5, PERPETUAL — khớp bảng mục 0; fundingInfo trả `fundingIntervalHours: 8`)
- [x] 6. JIT warm-up + benchmark numba vs rust ✅ (600k×16: numba 2.48s / **rust 2.27s** → chốt rust, lưu `config/vbt_settings.json`)
- [x] 7. Viết `config/settings.yaml` ✅
- [x] 8. Tạo `config/news_calendar.csv` ✅ (225 sự kiện: FOMC exact, NFP computed, CPI APPROX — verify BLS trước go-live; `scripts/gen_news_calendar.py`)
- [x] 9. Khung thư mục + `pyproject.toml` + `pip install -e .` ✅ (5 unit test data-layer pass)

**Exit criteria M0:** import vectorbt + 1 call API thật thành công; settings.yaml chứa mọi hằng số plan.

## M1 — Dữ liệu Binance thật (1.5 ngày)

- [x] 10. `src/solfut/data/binance_client.py` ✅ (retry + rate-limit 429/418 + funding_interval_hours động)
- [x] 11. `src/solfut/data/downloader.py` ✅ (monthly zip + REST tail; normalize ms/µs; detect header)
- [x] 12. Tải: M5 ✅ **631.145 nến, quality 0 lỗi / 1 gap (listing)**; D1/H1/funding — xem trạng thái dưới
- [x] 13. `resample.py` ✅ (H1/D1 + pivots UTC + round levels + ADR20, có test)
- [x] 14. `quality.py` ✅ (dedupe, gap, OHLC violation, quarantine, có test)
- [x] 15. `funding.py` ✅ (history + interval động — luật 17)
- [ ] 16. `calibrate_costs.py` — aggTrades + bookTicker 2 tháng gần nhất (chờ làm tiếp)
- [ ] 17. graphify build sau khi data layer ổn

**Exit criteria M1:** parquet M5/D1/H1/funding qua quality gate; bảng slippage có số thật; funding interval đọc động được.

## M2 — Features & filter chung (2.5 ngày)

- [ ] 18. `features/indicators.py` — EMA 13/20/25, MACD 12-26-9, ATR14, ADX14, RSI14, BB(20,2), KC(20,1.5), momentum 12 (vectorized, có unit test đối chiếu giá trị tay)
- [ ] 19. `features/patterns.py` — inside bar, powerbar, doji, reversal, outside, ii/ioi, kangaroo tail, big shadow
- [ ] 20. `features/state.py` — always-in, tight-TR (≤ 0.30×ADR20, kiểm chứng phân phối trước), barbwire, Impulse M30
- [ ] 21. `features/levels.py` — magnet round number + pivots UTC + swing + yesterday H/L
- [ ] 22. `features/context.py` — BTC D1 trend (EMA slope/ADX) + regime attribution bull/bear/chop; BTC-filter chỉ qua ablation, regime chỉ attribution
- [ ] 23. `features/orderflow.py` — taker imbalance/CVD từ trường taker-buy-volume klines; OI×giá 4 góc; funding sign
- [ ] 24. Activity filter: window 12:00–21:00 UTC, skip 10–11, blackout ±30' tin đỏ, ±5' mốc funding (interval động), weekend toggle
- [ ] 25. Unit test chống lookahead cho toàn bộ features (nến đóng mới sinh signal — bắt buộc)

**Exit criteria M2:** mọi feature có test; không hàm nào nhìn thấy tương lai (test lookahead pass).

## M2.5 — Event-study trước backtest (1.5 ngày)

- [ ] 26. `research/events.py` — forward-return có điều kiện vs baseline (+5m/+15m/+1h/+4h), moving-block bootstrap, decay curve, MFE/MAE; kill criteria pre-registered (excess ≥ 0.05% @+1h, t ≥ 2 TRAIN, giữ hướng VAL)
- [ ] 27. `research/hypotheses.py` — ledger: ID + tiêu chí pass/fail viết trước + verdict; cap giả thuyết/segment; ghi cả giả thuyết chết
- [ ] 28. `scripts/run_event_study.py` — chạy menu M2.6 (H1–H8) theo thứ tự giá trị kỳ vọng: H3 seasonality (rẻ nhất) → H2 BTC lead-lag → H4 OFI → H1 cascade fade → H6 carry (Track B) → H5/H7/H8
- [ ] 29. Chốt: giả thuyết nào pass → được vào M3; ghi verdict vào ledger

**Exit criteria M2.5:** ≥ 1 giả thuyết pass event-study cho mỗi chiến thuật được triển khai (cổng go/no-go 0).

## M3 — Ba chiến thuật ứng viên (4 ngày)

- [ ] 30. `strategies/base.py` — khung chung: Percent-Risk sizing, SL = cực trị trigger ± offset, cap SL, TP 2R, flat trong ngày, conflict resolver
- [ ] 31. S1 volman_breakout.py — 2 biến thể entry (stop-market taker + entry-retest maker)
- [ ] 32. S2 brooks_h2l2.py — H2/L2 + reversal bar + EMA20 pullback; biến thể always-in H1
- [ ] 33. S3 squeeze_pivot.py — TTM squeeze + confluence pivot/round
- [ ] 34. Mỗi chiến thuật ≥ 200 tín hiệu TRAIN (không nới ngưỡng — luật 3); tham số derive từ MFE/MAE của M2.5, grid chỉ fine-tune

**Exit criteria M3:** 3 chiến thuật sinh tín hiệu qua cùng interface, đủ mẫu, có unit test signal trên nến mẫu.

## M4 — Backtest engine (2 ngày)

- [ ] 35. `backtest/engine.py` — vectorbt broadcast 1 lần gọi (luật 14), freq 5min/15min, dual-bound same-bar SL-first/TP-first (chỉ lãi TP-first → loại — luật 8)
- [ ] 36. Fill rule maker: limit chỉ khớp khi giá đi XUYÊN QUA (trade-through); nếu không custom được → chạy cả touch-fill làm sensitivity bắt buộc
- [ ] 37. `backtest/costs.py` — BNB 0.018/0.045; maker-base + taker-worst song song, không định chính; funding theo interval động; slippage theo bảng M1; sensitivity ±50% + cost-shock MC; scale thanh khoản pre-2022
- [ ] 38. `backtest/monte_carlo.py` — shuffle lệnh + percentile DD + max losing streak
- [ ] 39. `backtest/robustness.py` — láng giềng tham số, leave-one-out, detector lag ±1/+2 nến, PBO/CSCV khi grid > 200 combo
- [ ] 40. `backtest/account.py` — $50 margin, qty làm tròn 0.01 SOL, check minNotional/qty/đòn bẩy ≤ 5× isolated
- [ ] 41. `backtest/metrics.py` — expectancy/SQN/PF/DD + gross/cost/net decomposition + regime attribution

**Exit criteria M4:** 1 grid đầy đủ chạy trong phút; cost model cho cả 2 kịch bản; tests sanity fills pass.

## M5 — Funnel & chống overfitting (3.5 ngày)

- [ ] 42. Splits: TRAIN 2020-10→2023-06 / VAL 2023-07→2024-06 / OOS#1 2024-07→2025-08 / WF 12m/3m / FINAL OOS#2 2025-09→2026-08 (đóng băng)
- [ ] 43. Grid fine-tune quanh tham số derive từ M2.5 (SL, TP R-multiple, offset, EMA, M5/M15, weekend)
- [ ] 44. Gates: gross dương zero-cost; net expectancy > 0.05R trong kịch bản execution được chọn (bootstrap CI không chứa 0); random-entry gate; ≥ 20 lệnh OOS/cửa sổ WF; không dồn 1 regime; reality-check cỡ mẫu (< 300 lệnh/năm → gộp chiến thuật)
- [ ] 45. DSR báo cáo cạnh mọi Sharpe; CPCV validation cho 1–2 ứng viên cuối
- [ ] 46. Pre-registration tiêu chí FINAL OOS#2 viết thành văn TRƯỚC khi chạy OOS
- [ ] 47. Chạy OOS#1 + WF stitched equity → chọn 1–2 ứng viên (chưa đụng FINAL OOS#2)

**Exit criteria M5:** ≥ 1 ứng viên pass toàn bộ gates; pre-registration đã ghi commit trước khi mở FINAL OOS#2.

## M6 — Live bot (4 ngày + testnet 4 tuần + mainnet nhỏ 1–2 tuần)

- [ ] 48. `live/bot.py` — dậy đúng nến đóng +2s; cùng module signal backtest; one-way, isolated, ≤ 5×, reduceOnly; bracket 2 lệnh + huỷ còn lại khi một bên khớp; state persistence idempotent
- [ ] 49. `live/risk_guard.py` — không lệnh thiếu SL; BE-only; 3 thua/−3% ngày dừng; −6% tuần dừng; cooldown tự reset; margin alert + kill-switch ≥ 10× SL; theo dõi số dư BNB; funding interval động
- [ ] 50. `live/health.py` — HealthMonitor + CircuitBreaker (mượn V1)
- [ ] 51. `live/journal.py` + `notify.py` — đối chiếu backtest↔live, cảnh báo Telegram/console
- [ ] 52. Testnet ≥ 4 tuần — chỉ nghiệm thu vận hành (không đối chiếu fill)
- [ ] 53. Mainnet size nhỏ 1–2 tuần (0.01–0.05 SOL) — so fills/slippage, lệch > 30% → hiệu chỉnh cost model; fill-rate post-only ≥ 60%
- [ ] 54. Live kill-switch: ≥ 50 lệnh, expectancy < 50% backtest hoặc PF < 1.0 → dừng về research

**Exit criteria M6:** testnet sạch vận hành + mainnet nhỏ khớp cost model ≤ 30% → mới bật live $50.

---

## Thứ tự thực thi tóm tắt

```
M0 (0.5d) → M1 (1.5d) → M2 (2.5d) → M2.5 (1.5d) → M3 (4d) → M4 (2d) → M5 (3.5d)
→ M6 (4d) → testnet 4 tuần → mainnet nhỏ 1–2 tuần → go-live $50
```

Cổng go/no-go: (0) sau M2.5 — mọi chiến thuật vào backtest phải có giả thuyết event-study pass; (1) sau M5 — gross + net pass toàn bộ gates; (2) sau testnet/mainnet-nhỏ — vận hành sạch + fills khớp ≤ 30%; (3) trước bật tiền thật đầy đủ.
