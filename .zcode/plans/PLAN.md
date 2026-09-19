# PLAN V2: Hệ thống giao dịch SOLUSDT Perpetual Futures trên Binance — Chuyển đổi từ plan EURUSD M5/MT5

> **Ngày:** 2026-09-19. Số liệu hợp đồng, funding, biến động đo trực tiếp từ Binance Futures API public tại thời điểm viết.
> **Bài học V1** (dự án `C:\Project\solusdt-future`, báo cáo 2026-09-14): framework đạt nhưng **edge NO-GO** — chi phí taker ~1.9 USD/lệnh gấp ~15 lần gross expectancy; gross ensemble −507 USD nhưng net −1,724 USD. V2 mã hóa các bài học này thành luật cứng (mục 11).

---

## 0. Thông số thật của hợp đồng (đo từ `fapi/v1/exchangeInfo` + `fapi/v1/fundingRate`, 2026-09-19)

| Thông số | Giá trị | Hệ quả cho hệ thống |
|---|---|---|
| Loại hợp đồng | PERPETUAL, USDT-margined | Không đáo hạn; funding 8h thay swap |
| Tick size (giá) | **0.01 USDT** | Mọi giá khớp bội số của 0.01 |
| Lot step / minQty | **0.01 SOL** | Sizing làm tròn xuống 0.01 SOL |
| Min notional | **5 USDT** | Vị thế < 5 USDT bị sàn từ chối |
| Đòn bẩy | Khuyến nghị cap **3–5× isolated** | SL luôn trước thanh lý (mục 8) |
| Phí VIP0 — **giả định toàn plan: trả phí bằng BNB** | Maker **0.018%** / Taker **0.045%** (BNB −10%; gốc 0.02%/0.05%). Funding fee **không** được giảm BNB | Từ `binance-fee/future.md`; user cam kết bật "Use BNB for Fees" trên tài khoản thật |
| Funding | Chu kỳ **8h (00/08/16 UTC)**; đo 500 kỳ gần nhất (≈166 ngày): **avg 0.0009%/kỳ, median 0.0017%, min −0.0388%, max 0.0100%**, 57% kỳ dương | Gần như bằng 0 cho lệnh đóng trong ngày; vẫn đưa vào cost model |
| Giá SOL tại thời điểm đo | 111.54 USDT | Mọi số USDT dưới đây theo mốc này, re-calculate định kỳ |
| ATR14 D1 | 4.96 USDT (**4.44%**); median range 200 ngày 3.09% | ADR dùng cho tight-TR filter & SL cap |
| ATR14 M5 | 0.224 USDT (**0.20%**); median range nến 5m 0.23 USDT | Mốc quy đổi khoảng cách Volman/Brooks |
| Profile giờ (UTC) | Cao điểm **13–19 UTC** (range 5m avg 0.28–0.47%, volume gấp 2–4×); chết nhất **10–11 UTC** (0.144%) | Thay phiên giao dịch FX (mục 4) |

## 0.1. Bảng quy đổi EURUSD → SOLUSDT (xương sống của V2)

Nguyên tắc: **không quy đổi theo "pip tương đương" tuyệt đối** (cấu trúc biến động khác nhau: SOL 5m ATR ≈ 5–7% ADR so với ~3% của EURUSD). Mọi khoảng cách **anchor theo ATR và % giá**, grid-search trong TRAIN.

| Khái niệm EURUSD (plan gốc) | Giá trị gốc | Quy đổi SOLUSDT | Lý do |
|---|---|---|---|
| 1 pip | 0.0001 (≈0.009% giá) | Không dùng — mọi khoảng cách theo **% giá hoặc bội ATR5m** | Tick 0.01 USDT quá mảnh để làm đơn vị "pip" |
| SL cap 15 pips (Brooks ≈12% ADR) | ≈5–7× ATR5m | **SL cap = max(3×ATR5m, 10%×ADR20)** ≈ 0.5–0.9 USDT (0.45–0.8%); grid **0.4–1.2%** | Hai anchor (ADR và ATR5m) hội tụ quanh 0.6–0.9 USDT |
| Bracket Volman 20/10 | TP 20, SL 10–15 pips | Giữ cấu trúc **TP = 2R**, grid TP 1.5R–3R | Tỷ số R là bất biến giữa thị trường |
| Entry offset 1 pip qua cực trị trigger | ≈0.3–0.5× ATR5m | **5–10 ticks (0.05–0.10 USDT ≈ 0.05–0.09%)**, grid {5, 10, 15} ticks | Giữ tương quan offset/noise ≈ 0.3–0.5× ATR |
| Magnet chặn 15 pips tới TP | | **0.15%** (≈0.17 USDT) | Cùng bậc tỷ lệ |
| Carter: confluence pivot ≤ 10 pips | | **≤ 0.10–0.15%** | Như trên |
| SL S3 max(20 pips, 2×ATR14) | | **max(0.25%, 2×ATR5m)**, grid | Như trên |
| Chi phí RT ≈ 0.7–1.2 pip (≈0.006–0.011%) ≈ **5–8% R** | Exness spread+slip | **Taker RT ≈ 0.09–0.11% ≈ 12–24% R; Maker-first RT ≈ 0.035–0.055% ≈ 5–11% R** (đã tính BNB −10%) | ⚠️ Khác biệt sống còn — xem mục 11, luật 1 |
| Phiên London+NY overlap, doldrums 12–14 CET | Giờ server EET | **Trade window 12:00–21:00 UTC** (đỉnh 13–19); **skip 10–11 UTC**; weekend = toggle grid (ON mặc định: crypto 24/7 nhưng volume cuối tuần mỏng) | Profile giờ đo được ở mục 0 |
| Flat trước cuối tuần | | Bỏ (thị trường 24/7), giữ **flat cuối ngày** | Không giữ qua đêm → tránh funding + gap |
| Swap −0.57 pip/đêm | | Funding đo được ≈ 0.001%/kỳ → ~0 nếu đóng trong ngày | Vẫn tính trong engine |
| Blackout tin đỏ ±30 phút | news_calendar.csv | **Giữ nguyên** (CPI/FOMC/NFP vẫn撬 động crypto) + thêm **±5 phút quanh mốc funding 00/08/16 UTC** | |
| Vốn $50 Exness cent lot | | **$50 USDT margin**, risk 1% = 0.5 USDT/lệnh | Mục 8 |

---

## 1. Kiến trúc dự án (trong `C:\Project\solusd-future-v2`)

```
solusd-future-v2/
├── config/settings.yaml        # symbol SOLUSDT, trade window UTC, risk, phí, tham số, funding times
├── config/news_calendar.csv    # tin đỏ macro 2020–2026 (CPI/FOMC/NFP) theo UTC
├── src/solfut/
│   ├── data/       binance_client.py (REST public), downloader.py (data.binance.vision bulk + REST),
│   │               resample.py, quality.py, funding.py
│   ├── features/   indicators.py, levels.py (round numbers 10 USDT, pivots UTC-00:00, zones), patterns.py, state.py
│   ├── strategies/ base.py, volman_breakout.py, brooks_h2l2.py, squeeze_pivot.py
│   ├── backtest/   engine.py (vectorbt wrapper), costs.py, metrics.py, account.py
│   ├── research/   splits.py, optimize.py, report.py, alpha_decomp.py
│   └── live/       bot.py (ccxt/python-binance), risk_guard.py, journal.py, notify.py
├── scripts/        download_data.py, calibrate_costs.py, run_backtest.py, run_walkforward.py, run_alpha_decomp.py, run_live.py
├── tests/          (unit + chống lookahead + sanity fills + cost model)
├── data/           (parquet — .gitignore), reports/
```

Khác v1 của EURUSD: `mt5_client.py` → `binance_client.py`; timezone thống nhất **UTC** (crypto native, hết bẫy DST của Exness EET); thêm `funding.py` và `alpha_decomp.py` (tách gross/cost — v1 đã chứng minh đây là phép đo sống còn).

## 2. M0 — Môi trường (½ ngày)
- venv `.venv`: `pip install pyarrow pyyaml pytest loguru ccxt python-binance` + `pip install -e C:\Project\vectorbt` (repo có sẵn, v1.1.0, numba cache bật, bắt buộc `freq="5min"`).
- Verify API: `curl https://fapi.binance.com/fapi/v1/ping` từ máy (đã xác nhận hoạt động).
- `config/settings.yaml`: toàn bộ hằng số kể từ bảng mục 0 — không hardcode.

## 3. M1 — Dữ liệu Binance THẬT (1–2 ngày)
- **Lịch sử bulk**: monthly zip M5 từ `data.binance.vision/futures/um/monthly/klines/SOLUSDT/` (từ 2020-09 khi listing perp → ≈ 630k nến M5); REST `fapi/v1/klines` (1500/req) cho phần gần nhất. Kèm D1, H1, funding history (`fapi/v1/fundingRate` full), mark price.
- `quality.py`: dedupe, gap check, OHLC violation, chuẩn hóa UTC (mượn pattern quality-gate/quarantine của V1).
- `resample.py`: M5→H1→D1; **pivots theo cắt UTC 00:00** (crypto không có session close — quy ước này là chuẩn crypto thay 17:00 NY của FX); round numbers bước **10 USDT** (100/110/120…, siết 5 USDT khi giá < 50); ADR20.
- `calibrate_costs.py`: từ aggTrades + bookTicker 2 tháng gần nhất → bảng **slippage thực tế theo giờ & theo size**; đối chiếu spread.

## 4. M2 — Features & bộ filter chung (2–3 ngày, có unit test)
- `indicators.py` giữ nguyên: EMA 13/20/25, MACD 12-26-9, ATR14, ADX14, RSI14, BB(20,2), KC(20,1.5), momentum 12.
- `patterns.py` giữ nguyên định nghĩa sách: inside bar, powerbar, doji, reversal bar, outside bar, ii/ioi, kangaroo tail, big shadow.
- `state.py`: always-in (Brooks), tight-TR (range N bar ≤ 0.30×ADR20 — **ADR crypto lớn hơn, filter này sẽ nới tay hơn FX, kiểm chứng phân phối trước**), barbwire, Impulse M30 (Elder).
- `levels.py`: magnet = round number gần nhất + pivot daily/weekly (UTC) + đỉnh/đáy swing + yesterday H/L. *(Nâng cao, phase 2: funding-rate cực đoan làm sentiment magnet.)*
- **Thay session filter FX bằng activity filter**: trade chỉ trong **12:00–21:00 UTC** (đo được ở mục 0), skip 10–11 UTC; blackout ±30' tin đỏ macro; blackout ±5' quanh funding 00/08/16 UTC; toggle weekend (mặc định OFF cuối tuần, grid kiểm chứng). Flat cuối ngày → không giữ qua mốc funding nào.

## 5. M3 — Ba chiến thuật ứng viên (3–5 ngày) — giữ nguyên logic sách, re-anchor khoảng cách theo bảng 0.1

Chung: risk 1% (0.5 USDT)/lệnh, Percent-Risk sizing (Tharp), SL = cực trị signal bar ± offset (5–10 ticks), cap SL theo bảng 0.1, TP 2R, một vị thế, đóng trong ngày. **Mỗi chiến thuật phải sinh ≥ 200 tín hiệu trong TRAIN — chiến thuật "đói tín hiệu" như mean_reversion của V1 (2 lệnh/540 ngày) bị loại ngay, không nới ngưỡng tùy ý.**

- **S1 — Volman Breakout**: box tight ≥3 bar đè sát barrier (round number/pivot/box extreme); trigger inside bar hoặc powerbar+inside combi; entry **stop-market** 5–10 ticks qua cực trị; filter 25 EMA slope, không adverse magnet 0.15% tới TP, không tight-TR, không entry từ xa.
- **S2 — Brooks H2/L2 Pullback**: always-in M5; H2/L2 + reversal bar; pullback ≥40% chạm EMA20; entry 1 offset qua signal bar; TP 2R (nửa 1R + BE phase 2); cấm tight-TR/barbwire; second entry.
- **S3 — TTM Squeeze + Pivot**: squeeze ON/OFF như Carter; confluence pivot/round ≤ 0.10–0.15%; entry market (taker — tính phí); SL max(0.25%, 2×ATR5m); exit momentum roll-over hoặc 2R.
- Meta-parameter: **M5 vs M15** cho cả 3 chiến thuật (SOL 5m nhiễu hơn EURUSD; V1 chạy 15m) — quyết định qua funnel, không đoán.
- **Ưu tiên phát triển maker-first (thứ tự thiết kế bắt buộc):** (1) mỗi chiến thuật được phát triển thử entry **post-only limit** tại/qua cực trị trigger trước; (2) chỉ dùng **stop-market taker** khi cấu trúc chiến thuật bắt buộc (S1 breakout momentum). S2/S3 vốn entry limit/pullback → maker-friendly tự nhiên; S1 bản chất taker → phải tự chứng minh gross đủ lớn để trả phí taker. Funnel báo cáo thêm **maker-share** (tỷ lệ lệnh khớp maker) và fill-rate post-only cho từng chiến thuật, song song với PnL.

## 6. M4 — Backtest engine vectorbt (2 ngày)
- `engine.py` wrap `Portfolio.from_signals` như plan gốc: intrabar OHLC fills, **cùng bar chạm SL+TP → SL trước**, `freq="5min"` (hoặc 15min nếu meta chọn M15).
- `costs.py` — **mọi phí theo giả định BNB: maker 0.018% / taker 0.045%**; 2 kịch bản, **maker-base là kịch bản chính** (hướng phát triển maker-first), taker-worst chỉ là stress:
  - `maker-base` (**chính**): entry post-only limit tại trigger (mô hình **non-fill + adverse selection** — bài học V1 mục 9.5.5), TP limit maker 0.018%, SL taker 0.045% + slippage. RT kỳ vọng ≈ 0.035–0.055%.
  - `taker-worst` (stress): entry stop-market taker 0.045%, SL stop-market taker + slippage 1–2 ticks đo được, TP limit maker 0.018%. RT ≈ 0.09–0.11%.
  - Funding: tính khi vị thế băng qua 00/08/16 UTC (mặc định 0 vì flat trong ngày).
  - Sensitivity ±50% phí + cost-shock Monte Carlo (mượn từ V1); ±50% quanh mức BNB bao trùm cả trường hợp **hết BNB → revert phí gốc 0.02%/0.05% (+11%)**.
- `account.py`: equity $50 USDT; qty = risk / SL_distance, làm tròn xuống 0.01 SOL; **check minNotional ≥ 5 USDT, qty ≥ 0.01 SOL, đòn bẩy hiệu dụng ≤ 5× isolated**. Ví dụ: risk 0.5 USDT, SL 0.7 USDT → 0.71 SOL ≈ 79 USDT notional ≈ 1.6× — nằm gọn trong cap, và SL (−0.7%) luôn kích hoạt trước thanh lý (5× isolated → liquidation ≈ −19%).
- `metrics.py`: như plan gốc (expectancy > 0.05R sau chi phí, SQN ≥ 2.0, PF ≥ 1.3, ≥ 100 trades/segment, maxDD ≤ 25%) **+ phân rã gross/cost/net theo chiến thuật (alpha decomposition — bắt buộc từ V1)**.

## 7. M5 — Chia dữ liệu & Funnel (3–4 ngày) — chống overfitting (SOL perp từ 2020-09, dời mốc tương ứng)
1. **TRAIN** 2020-10 → 2023-06 — nghiên cứu, grid (SL 0.4–1.2%, TP 1.5–3R, offset {5,10,15} ticks, EMA 18–30, M5/M15, weekend toggle).
2. **VALIDATION** 2023-07 → 2024-06 — chọn params/chiến thuật.
3. **TEST OOS#1** 2024-07 → 2025-08 — chỉ chạy khi đã chốt.
4. **WALK-FORWARD**: train 12 tháng / test 3 tháng, cuốn 2020→2025; stitch equity OOS.
5. **FINAL OOS#2** 2025-09 → 2026-08 — không đụng tới đến lúc quyết định go-live.

Cổng sống sót giữ nguyên từ plan gốc (Tharp/Elder) **+ gate riêng của V2**:
- Gross expectancy (zero-cost, cùng tập lệnh) phải **dương** trước khi nói gì đến phí — nếu gross âm thì sửa hypothesis, không dùng maker để cứu (V1 mục 9.5.3).
- Expectancy sau chi phí **trong kịch bản maker-base (kịch bản chính)** > 0.05R; taker-worst được báo cáo làm stress, chấp nhận âm nhẹ nhưng phải ghi rõ điều kiện sống.
- Baseline V1 (trend_pullback zero-cost +0.12R/lệnh, PF 1.014) làm **negative control tham chiếu**.

## 8. M6 — Live Bot Binance (3–4 ngày + demo 4 tuần)
- `bot.py`: dậy đúng nến M5 đóng (+2s) qua websocket kline hoặc poll REST; gọi **cùng module signal của backtest**; `order_send` qua ccxt/python-binance với: **one-way mode, isolated, leverage ≤ 5×, SL/TP là order giảm chỉ thị (reduceOnly)**, magic qua `newClientOrderId`.
- `risk_guard.py` — luật cứng (giữ nguyên plan gốc + bổ sung Binance): không lệnh thiếu SL; stop chỉ siết về BE; 3 thua hoặc −3% ngày → dừng ngày; −6% tuần → dừng tuần; **loss-streak cooldown phải tự reset theo thời gian (bug đóng băng vĩnh viễn của V1)**; blackout tin; **margin-ratio alert + kill-switch trước khi chạm thanh lý** (dư địa ≥ 10× khoảng cách SL); API key chỉ Futures, không rút tiền, IP whitelist.
- **BNB trả phí (giả định toàn plan)**: bật "Use BNB for Fees" khi setup tài khoản Futures; `risk_guard.py` theo dõi số dư BNB ví Futures — dưới ngưỡng tối thiểu (≈ 2 tuần phí dự kiến) → cảnh báo qua `notify.py`; hết BNB → phí revert 0.02%/0.05% (mất ưu đãi −10%) → flag vào `journal.py` vì mọi giả định cost model lệch đi. Funding fee **không** giảm BNB.
- Vận hành: reconnect, restart rollover, `journal.py` đối chiếu backtest↔live.
- **Lộ trình go-live**: **Binance Futures Testnet ≥ 4 tuần** → so fills/spread/slippage live với giả định backtest (lệch > 30% → hiệu chỉnh cost model) → live $50 margin, leverage 5× isolated cap. VPS chạy 24/7.

## 9. Rủi ro nhận diện & biện pháp
- **Chi phí taker giết edge** (bằng chứng V1) → **maker-first là hướng phát triển ưu tiên số 1** (entry post-only trước, taker chỉ khi cấu trúc bắt buộc) + gate gross-trước-phí + alpha decomposition bắt buộc.
- **Hết BNB / quên bật "Use BNB for Fees"** → phí revert 0.02%/0.05% (mất ưu đãi −10%, taker RT lên ~0.10–0.12%) → `risk_guard.py` theo dõi số dư BNB; sensitivity ±50% đã bao trùm trường hợp này.
- Post-only limit có thể không khớp → mô hình non-fill + adverse selection; đo fill-rate thật trên testnet (mục tiêu ≥ 60%).
- SOL 5m ADR/ATR khác EURUSD → mọi khoảng cách qua grid TRAIN, không hardcode theo pip.
- Funding cực đoan (min đo được −0.039%) → flat trong ngày loại trừ gần hết; vẫn mô hình hóa.
- Price action sách khó codify 100% → subset máy móc, rating ≤ 3, cross-check nguồn (giữ nguyên plan gốc).

## 10. Thứ tự & thời gian (≈ 3 tuần làm việc)
M0 (0.5d) → M1 (1.5d) → M2 (2.5d) → M3 (4d) → M4 (2d) → M5 (3.5d) → M6 bot (4d) → testnet 4 tuần → go-live $50.
Cổng go/no-go: (1) sau funnel M5 — cả gross lẫn net maker-base phải pass; (2) sau testnet — fills khớp giả định; (3) trước bật tiền thật.

## 11. Luật cứng rút từ V1 (không được vi phạm)
1. **Maker-first là điều kiện sống còn VÀ hướng phát triển ưu tiên, không phải tối ưu hóa.** V1 chết vì taker RT ≈ 15–25% R. Mọi chiến thuật phát triển theo thứ tự: entry post-only trước, stop-market taker chỉ khi cấu trúc bắt buộc.
2. Gross alpha phải dương ở zero-cost trên cùng tập lệnh trước mọi thí nghiệm execution.
3. Chiến thuật đói tín hiệu (mẫu < 200 trong TRAIN) bị loại, không nới ngưỡng.
4. Mọi run phải ghi `run_id` + config hash + manifest; holdout cuối kỳ đóng băng.
5. Loss-streak cooldown tự reset theo thời gian; không bao giờ đóng băng vĩnh viễn.
6. Chi phí đo từ aggTrades thật, không giả định; sensitivity ±50% bắt buộc.
7. **Toàn bộ plan tính phí theo BNB** (maker 0.018% / taker 0.045%): phải bật "Use BNB for Fees" và giữ đủ số dư BNB trên tài khoản thật; hết BNB → phí +11% so với giả định, phải re-check cost model. Funding fee không giảm BNB.
