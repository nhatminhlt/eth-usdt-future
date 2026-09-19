# RESEARCH WAVE 1 + 2 — BÁO CÁO TỔNG KẾT (2026-09-20)

## Verdict: NO-GO cho giao dịch intraday→4h trên Binance perp với vốn $50 — sau 43 kiểm định pre-registered (7 event-study pass, 36 kill; MỌI trading implementation đều kill)

Chương trình nghiên cứu Wave 1 (M0→M5 funnel tới cổng go/no-go số 0) đã chạy ĐỦ theo PLAN:
mọi giả thuyết có tiêu chí pass/fail viết trước khi test (luật 13), mọi kết quả kể cả chết
đều ghi ledger. Không có chiến thuật nào vượt qua đầy đủ TRAIN gate + VAL confirm.

## 1. Những gì ĐƯỢC chứng minh (tài sản tri thức của dự án)

### 1a. Lớp edge "BTC seesaw fade" là THẬT — nhưng chỉ trong regime vol cao, và đã tắt từ 2023
- BTC 5m rơi ≥2σ → alt (SOL/ETH/DOGE/AVAX) có drift hướng LÊN đo được, **replicate 4/4 symbol**
  cùng định nghĩa pre-registered: excess @+1h: SOL +0.152% (t=6.7), ETH +0.054% (t=3.3),
  DOGE +0.101% (t=3.7), AVAX +0.180% (t=7.7); n=7,479 events trên window TRAIN 2020-10→2023-06.
- Drift tăng theo horizon tới +4h/+24h; tier **vol cao (atrPct 30d > 70)** lift drift 2.2–3.1×
  trên MỌI symbol (SOL +0.83%, AVAX +0.55%, DOGE +0.45%, ETH +0.26% @4h).
- Implementation 4-symbol portfolio (horizon exit 4h, SL thiên tai |MAE q05|, governed sizing
  1× / risk cap 3%): **TRAIN +0.017R (CI [+0.0025, +0.032] > 0), SQN 2.57, ~+29%/năm, +183 USDT
  trên 4×$50** — dương có ý nghĩa thống kê NHƯNG dưới gate 0.05R, và:
- **VAL 2023-07→2024-06: ÂM toàn bộ** (portfolio −0.011R, PF 0.87; cả 4 symbol ≤ 0).
  Event-drift mức VAL đã co (~+0.24% SOL tier vs +0.83% TRAIN) → sau chi phí không còn gì.
- Giải thích cơ chế: seesaw bounce = thanh khoản khẩn cấp refill sau forced selling — tồn tại
  khi market stress (2020 covid, 2021 mania, 2022 Luna/FTX); biến mất trong grind 2023-24.

### 1b. Những gì KHÔNG có edge (đã kill, có bằng chứng)
- Sách FX (S1 Volman / S2 Brooks H2L2 / S3 Squeeze): 6/6 atoms KILL — luật 16 đúng.
- Seasonality giờ/mốc nến/funding (H3a/b/c): KILL.
- Taker-surge reversal (H4a2): chỉ đúng trên SOL, **không replicate** → artifact.
- OI squeeze (H4d): KILL mọi tầng.
- Cascade fade proxy (H1): KILL (n=584, CI chứa 0).
- TSMOM D1 (H7): KILL cả long lẫn short — state-flip EMA20 quá muộn trên altcoin beta cao.
- Funding carry (H6): percentile thuần KILL (churn); sàn tuyệt đối 0.02%/mark: mean +0.90%/
  cycle, CI > 0, NHƯNG chỉ mania (2021 +18.9% notional; 2022-23 ≈ 0) — median < gate → KILL
  theo pre-registration. Carry là thu nhập phụ mania-conditional, không phải edge độc lập.

### 1c. Các định luật chi phí đã được đo, không giả định
- Taker RT ≈ 0.127% notional (fee 0.045% BNB + slippage 0.019%×2, stop mult 1.03 đo từ
  aggTrades); maker entry-retest RT ≈ 0.075%. Drift fade 1h (0.05–0.18%) < RT → mọi chiến
  thuật intraday thuần chết ở cost model; chỉ horizon ≥ 4h mới có cơ hội — và chỉ 2020-22.
- $50 equity + minNotional (SOL/DOGE/AVAX 5 USDT, **ETH 20 USDT**) + SL thiên tai 7–11%
  → percent-risk sizing chạm sàn notional; governed sizing (min(equity×lev, equity×cap/sl)
  với floor minNotional + guard) là model đúng cho lớp wide-stop.

## 2. Hạ tầng hoàn thành (tái sử dụng cho mọi Wave sau)
- Data: 4 symbol × 5m full (SOL 2020-09→2026-09; 3 symbol 2020-10→2024-07), BTC 5m/D1,
  funding 4 symbol, OI SOL, aggTrades calibration, symbol specs snapshot.
- Engine: taker/maker trade-through fills, same-bar 2-bound, flat-EOD, funding thật,
  governed + percent-risk sizing, conflict resolver, activity mask (option).
- Metrics: gross/cost/net decomposition, bootstrap CI moving-block, regime attribution,
  MC drawdown, random-entry baseline. 27 unit tests (fill rules, bounds, costs, sizing,
  lookahead guards).
- Quy trình: hypothesis ledger pre-registered (38 rows, cap/segment), splits đóng băng,
  event-study machinery (excess, decay, MFE/MAE, block bootstrap).

## 3. WAVE 2 — nguồn thông tin mới: H5 premium basis (2026-09-20, cùng ngày)
- Data: REST `fapi/v1/premiumIndexKlines` SOLUSDT 5m 2020-10→2024-07 (396k bars) — vision 404
  (claim cũ của PLAN sai, probe trực tiếp bắt được).
- **H5a (premium > p95 → short drift): KILL** — dấu ngược (ex −0.037% @1h): crowding long KHÔNG
  đảo ngay, premium cao vẫn momentum.
- **H5b (premium < p5 → long drift): PASS event-study** — ex +0.094% @1h (t=4.17), +0.180% @4h
  (t=4.22, knee decay curve), n=15,116, VAL giữ hướng (+0.023%). Pass event-study THỨ 7.
- **Implementation (luật 12): KILL** — TRAIN governed/taker +0.0003R (PF 0.99); maker +0.006R;
  percent-risk/taker n=0 (notional 0.5/0.1059 = 4.72 < minNotional 5 — bức tường hợp đồng).
- **Số học bất khả đã được chứng minh 2 wave:** r_net ≈ (drift×capture − RT)/sl. Với SL thiên tai
  6–11% (bản chất fade multi-hour) và capture 60–100%, cần drift > ~0.8%/event để vượt gate
  0.05R — chỉ tier cực đoan đạt, và tier đó không sống VAL 2023-24. Mỗi drift ≤ 0.3% đều chết.

## 4. Điều kiện re-evaluation (Wave 3+)
1. **Nguồn thông tin MỚI** (không phải xoay bánh trên cùng data): H5 premium/basis index
   (data.binance.vision có history), H8 Deribit 25Δ risk-reversal (D1 context, evidence
   mạnh nhất menu — Neo 2026). Cần segment ledger mới theo nguồn dữ liệu.
2. **Regime gate tuyệt đối**: edge chỉ sống ở high-stress — gate trên BTC realized-vol
   ABSOLUTE (không phải rolling rank) sẽ tự tắt trong grind; trade-off: lệnh hiếm đi
   (< 300/năm → vi phạm reality-check → chỉ đáng làm khi gộp nhiều symbols/tần suất).
3. **Vốn lớn hơn / danh mục rộng hơn**: không đổi R-economics nhưng đổi khả năng vào
   minNotional ETH và giảm tỷ trọng fixed cost; multi-symbol portfolio hạ DD.
4. **OOS1 2024-07→2025-08 CHƯA ĐỤNG** — chỉ chạy khi có cấu hình frozen từ Wave 2.

## 5. Bài học ghi vào luật (bổ sung PLAN mục 11)
18. **Event-drift ≠ tradeable PnL**: phép đo close-to-close bỏ qua path (SL hits, subset
    selection do single-position, EOD truncation). Implementation capture 60-100% drift tùy
    symbol; mọi claim edge phải qua engine, không kết luận từ event-study.
19. **Sizing phải theo lớp horizon**: wide-stop strategies dùng governed sizing (worst-case
    risk cap + floor minNotional + guard), percent-risk trên SL rộng tự giết R-economics.
20. **Session filter chỉ dành cho intraday**: với hold ≥ 4h, filter giờ cắt 56% events mà
    drift không đổi — mặc định OFF cho lớp horizon.

Ledger cuối: 43 rows — 7 pass event-study (H2b SOL+ETH+DOGE+AVAX, H4a2 SOL, H4d SOL, H5b SOL), 36 kill, mọi implementation kill. Số liệu: data/reports/*.json.
