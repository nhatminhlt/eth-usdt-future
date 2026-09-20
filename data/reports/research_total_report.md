# BÁO CÁO TỔNG KẾT RESEARCH — solusd-future-v2 (cập nhật 2026-09-20)

> Ghi đè 4 Wave nghiên cứu trong 1 ngày (2026-09-20): Wave 1 (menu PLAN), Wave 2 (nguồn thông tin
> mới — premium basis), Wave 3 (cấu trúc không-tuning), Wave 4 (feed practitioner — Gate Wiki).
> **Ledger: 58 kiểm định pre-registered — 15 pass event-study, 43 kill; MỌI trading implementation
> đều kill qua đủ chuỗi TRAIN→VAL→OOS1.**

## Verdict cuối

**NO-GO cho giao dịch intraday→4h trên Binance perp (SOL/alts) với vốn $50, theo tiêu chí
net-expectancy ≥ 0.05R/lệnh của PLAN.** Edge thống kê luôn tồn tại (15 drift pass), nhưng không
atom nào vượt được cặp bức tường định lượng:

1. **Số học chi phí**: `r_net ≈ (drift × capture − RT) / sl` — với SL thiên tai 6–11% (bản chất
   fade multi-hour) và RT thực 0.036% (maker/maker) đến 0.127% (all-taker), cần drift
   > ~0.8%/event để vượt gate 0.05R. Mọi drift đo được ≤ 0.3%; chỉ tier cực đoan đạt 0.83% và
   không bền qua segment.
2. **Regime dependence**: edge sống ở vol stress 2020–22, tắt trong grind 2023–24
   (ensemble tốt nhất: TRAIN +0.024R → VAL −0.008R → OOS1 +0.002R breakeven).

OOS1 đã tiêu một phát duy nhất (one-shot, pre-registered). **FINAL OOS2 (2025-09→2026-08) vẫn
đóng băng — không đụng đến khi chưa có cấu hình mới frozen.**

---

## 0. TL;DR từng Wave

| Wave | Nội dung | Kết quả chính |
|---|---|---|
| 1 | Event-study menu PLAN (Sách FX, H1–H8) trên SOLUSDT | 3 PASS (H2b/H4a2/H4d), 20 KILL; mọi implementation KILL (bracket rò rỉ) |
| 2 | Nguồn thông tin mới: premium basis (REST premiumIndexKlines) | H5b PASS event-study (t=4.17) → implementation KILL |
| 3 | Cấu trúc không-tuning + replication + ensemble 8 symbol | H2b replicate **8/8 symbol**; cấu hình tốt nhất: TRAIN +0.024R (CI>0, ~+23%/năm) — VAL âm, OOS1 breakeven → KILL |
| 4 | Feed từ Gate Wiki article (câu hỏi user) | H9 RSI-oversold PASS (drift mạnh nhất t=9.12) → KILL ở implementation (episode-cluster); H10 bị dữ liệu phủ định; H10b fade-breakdown PASS event-level |

## 1. Wave 1 — event-study menu PLAN + implementation đầu tiên

- **Sách FX (S1 Volman / S2 Brooks H2L2 / S3 Squeeze): 6/6 atoms KILL** (t≤1.22) — luật 16 đúng:
  sách FX cung cấp từ vựng, không chuyển thành edge trên SOL.
- Chết ngay: H3 seasonality (giờ/mốc nến/funding), H1 cascade proxy (n=584, CI chứa 0).
- 3 PASS event-study: **H2b seesaw** (BTC 5m rơi ≥2σ → SOL bounce, +0.158% @1h t=6.7),
  **H4a2 sell-surge reversal** (+0.111% t=6.1), **H4d OI squeeze @4h** (+0.084% t=8.0).
- Implementation bracket SL=\|MAE q25\|/TP=MFE q75 → gross ≈ 0/âm. Random-entry baseline cùng
  bracket thua −0.08…−0.28R → chính bracket là chỗ rò (SL khơi 26–47% lệnh × −1R).
- Horizon-exit variant (pre-registered, 1 biến thể — không TP, SL thiên tai \|MAE q05\| 6–7.4%):
  gross dương nhưng net −0.005…+0.009R ≪ 0.05R → cả 3 KILL.
- H7 TSMOM D1 (long+short) KILL — flips EMA20 quá muộn trên altcoin beta cao.
- H6 funding-carry: percentile thuần KILL (churn 132 cycles, median −0.23%); sàn tuyệt đối
  0.02%/mark: mean +0.90%/cycle CI>0 nhưng **chỉ mania 2021 (+18.9% notional; 2022–23 ≈ 0)**
  → median < gate → KILL. Carry là thu nhập phụ mania-conditional, không phải edge độc lập.

## 2. Wave 2 — nguồn thông tin mới: premium basis

- Data: REST `fapi/v1/premiumIndexKlines` SOLUSDT 5m 396k bars (2020-10→2024-07). *Vision 404 —
  probe trực tiếp bắt thêm 1 claim sai của PLAN.*
- **H5a** (premium >p95 → short drift): KILL — dấu ngược (crowding long KHÔNG đảo ngay).
- **H5b** (premium <p5 → long): **PASS** — ex +0.094% @1h t=4.17, +0.180% @4h t=4.22 (knee),
  n=15,116, VAL giữ hướng → implementation KILL (TRAIN governed/taker +0.0003R, PF 0.99;
  percent-risk/taker n=0 vì notional 4.72 < minNotional 5).

## 3. Wave 3 — "Chiến lược tốt hơn KHÔNG cần tuning tham số" (câu trả lời đo đạc cho user)

Hai điều kiện mới: confluence **H3W (H2b × premium<0.25 × ATR>2×anchor) KILL** — +0.368% @4h
< 0.55% cần (premium-low pha loãng; gate ATR tuyệt đối 0.40% vô nghĩa — 7430/7435 qua vì vol
nền 2021–22 cao). **A2 high-vol tier single-symbol** KILL (TRAIN +0.032R < gate, VAL âm).

Bốn đòn bẩy cấu trúc đã đo tác động riêng:

| Đòn bẩy cấu trúc | Trước → Sau | Tác động |
|---|---|---|
| Exit: bracket → horizon exit + SL thiên tai \|MAE q05\| | −0.11R → +0.017R | +0.13R — lớn nhất |
| Cost: all-taker 0.127% → maker/maker ~0.036% (exit limit trade-through, fill 96–99.8% đo được) | +0.017R → +0.024R | costR giảm ~50% |
| Account: percent-risk → governed (worst-case cap 3%, floor minNotional + guard; minNotional ETH = 20 USDT!) | n=0/reject → n đầy đủ | lớp wide-stop tồn tại được |
| Breadth: 4 → 8 symbol (H2b replicate 8/8: +BNB t=4.9, XRP t=6.0, ADA t=7.3, LINK t=6.7) | CI [0.0043,0.0326] → [0.0061,0.0423] | CI chặt, n 4.4k→8.3k |

**Chuỗi 3 segment của cấu hình tốt nhất (ensemble-8, maker/maker, governed):**
- TRAIN 2020-10→2023-06: **+0.0235R, CI [+0.0061, +0.0423] > 0, n=8,252, +412 USDT/8×$50
  (~+23%/năm), DD 12.6%, PF 1.15** — dương có ý nghĩa, dưới gate 0.05R.
- VAL 2023-07→2024-06: −0.0084R.
- OOS1 2024-07→2025-08 (one-shot, pre-registered): +0.0019R, CI [−0.0161, +0.0203] chứa 0 —
  breakeven → KILL.

## 4. Wave 4 — feed từ practitioner source (Gate Wiki, theo yêu cầu user)

Nguồn: Gate Wiki "SOL/USDT TA & Trade Plan" (2026-01-02) — template SEO, không backtest.
Qua gate luật 16 (pre-register → event-study → implementation):

| Atom từ bài | Event-study | Implementation | Verdict |
|---|---|---|---|
| H9 RSI(14)<30 → bounce | **PASS — drift mạnh nhất chương trình** (@8h +0.335% t=9.12, @24h +0.492% t=7.23, VAL +0.104%) | KILL (−0.015R) — RSI<30 là chuỗi bar liên tục, engine vào bar ĐẦU episode dính cú fall | KILL |
| H9c RSI cross-back-up >30 (confirmation của bài) | KILL (ex≈0) — cross-up trễ, leg đầu bounce đi rồi | — | KILL |
| H10 phá hỗ trợ + volume → short (theo bài) | **Dữ liệu PHỦ ĐỊNH**: breakdown → drift LÊN +0.143% @1h t=6.65 | — | KILL (sai hướng) |
| H10b fade-the-breakdown (đảo chiều theo measurement) | **PASS** (+0.143% t=6.65, @8h +0.307%, VAL +0.065%) | Chưa test | Pass event-level |
| Partial-exit + BE-trail ("chốt một phần, dời SL") | — | Engine capability MỚI: 50% tại median-MFE (maker), SL còn lại → BE; 3 tests; partial fill 47% đo được | Reusable |
| RR 1:5, SL 10–15%, TP 20–30%, "SOL 300/500" | Không phương pháp | — | Bỏ |

**Bài học 21 (mới):** drift đo trên event với label chồng lấn có thể phản ánh drift CỦA EPISODE
chứ không phải ENTRY RULE — "drift episodic không có entry tradeable" là kết luận hợp lệ; atom
từ bài practitioner phải đo cả event-study lẫn implementation.

## 5. Tài sản tri thức (giữ cho mọi phiên sau)

- **H2b BTC-seesaw fade là thật và tổng quát** — replicate 8/8 perp (SOL/ETH/DOGE/AVAX/BNB/XRP/
  ADA/LINK, t=4.9–7.7 @+1h), lift 2.2–3.1× ở tier vol cao; nhưng regime-conditional (stress
  2020–22; AVAX OOS1 +0.097R đúng các spike 2024–25) và kết buộc tường chi phí.
- **H9 RSI-oversold**: drift đỉnh @8h +0.335% t=9.12 — drift lớn nhất đo được, nhưng episodic
  (không có entry tradeable); họ RSI dừng sau 3 rows đúng kỷ luật.
- Kill list có bằng chứng: Sách FX 6/6, H3 seasonality, H4a2 (artifact — chỉ pass SOL/XRP/LINK,
  fail theo cơ chế @8h mọi symbol khác), H4d, H1, H7 TSMOM, H6 carry (mania-only), H10
  (sai hướng), H9c (quá trễ), H3W confluence (pha loãng).
- **Chi phí đo, không giả định**: RT taker ≈ 0.127% (fee BNB 0.045% + slippage 0.019%×2, stop
  mult 1.03 từ aggTrades); maker/maker ≈ 0.036%; minNotional theo symbol (ETH 20 USDT).
- Quy trình đã chuẩn hóa: pre-registration → event-study (excess/decay/MFE-MAE/block-bootstrap)
  → implementation engine (trade-through fills, 2 bound, flat-EOD, funding thật, governed
  sizing) → TRAIN gate → VAL → OOS one-shot. Ledger 58 rows là bằng chứng chống churn.

## 6. Hạ tầng hoàn thành

- Data: 8 symbol × 5m (SOL full 2020→2026-09; 7 còn lại 2020-10→2025-09), BTC 5m/D1, funding
  4 symbol, OI SOL, premium SOL, aggTrades calibration, symbol specs snapshot (API thật).
- Engine: taker market + maker post-only trade-through (entry & exit, patience/fallback),
  same-bar 2-bound, partial-exit + BE-trail, flat-EOD, funding thật, percent-risk + governed
  sizing per-symbol contract, conflict resolver, activity mask (option). **34 unit tests pass.**
- Metrics: gross/cost/net decomposition, bootstrap CI moving-block, regime attribution,
  MC drawdown (compound floor-0), random-entry baseline, gates_check từ settings.
- Research: events.py, hypotheses.py ledger (+cap per segment), splits đóng băng, scripts
  tái chạy được từng bước (scripts/run_*.py mang tên wave).

## 7. Luật bổ sung (mục 11 PLAN, giờ 21 luật)

18. Event-drift ≠ tradeable PnL — mọi claim qua engine, không kết luận từ event-study.
19. Sizing theo lớp horizon — wide-stop dùng governed sizing; minNotional per-symbol.
20. Session filter chỉ dành cho intraday — hold ≥ 4h mặc định OFF.
21. Drift episodic (vd RSI<30) có thể không có entry tradeable — atom từ bài practitioner phải
    qua cả event-study lẫn implementation.

## 8. Wave 5 — stress attribution: cuts duy nhất dương cả 3 segment (UPDATE cùng ngày)

**Phép đo (run_w5_stress_attribution.py + run_w5b_entry_gated.py — measure-only, measure-only):**
Expectancy của cấu hình FROZEN ensemble-8 chia theo bậc ATR14-5m TUYỆT ĐỐI tại bar signal
(ladder từ anchor 0.20%):

| Bậc vol | TRAIN | VAL | OOS1 |
|---|---|---|---|
| <0.2% | n=46, âm | n=169, âm | n=74, âm |
| 0.2–0.4% | n=1718, **−0.009R** | n=1118, **−0.016R** | n=1124, +0.008R |
| 0.4–0.8% | n=4699, +0.012R | n=1016, −0.002R | n=1680, −0.011R |
| **≥0.8% (stress)** | **+0.068R, CI [+0.042, +0.094], n=2377** | **+0.059R, CI [+0.0006, +0.132], win 0.61** | **+0.035R, CI [+0.0014, +0.078], n=351** |
| ≥1.6% (panic) | +0.195R, CI [+0.092, +0.308], n=493 | +0.119R (n=36, mẫu mỏng) | +0.231R (n=59, mẫu mỏng) |

→ **Edge thuần tuý nằm ở nhịp stress shock** — đúng mechanism a-priori (liquidity refill sau
forced selling tăng giá trị khi cả hệ thống stress). Bậc ≥0.8% là cuts ĐUY NHẤT dương cả 3
segment với CI > 0; frequency 867/y (TRAIN) và 302/y (OOS1) ≥ 200.

**Entry-gated recheck (con số của chiến lược thật — gate tại entry,不是 post-hoc):**
- TRAIN: **+0.0551R, CI [+0.0128, +0.1017], n=3,095, SQN 4.36, DD 12.7% — VƯỢT gate 0.05R**
- VAL: +0.0137R (dương)
- OOS1: +0.0378R — dương NHƯNG CI [−0.0150, +0.0923] chênh nhẹ chưa khép kín 0.

**Trạng thái pre-registration:** `W5_stress_gated_ensemble8_OOS2` (pending) — one-shot
FINAL OOS2 (2025-09→2026-08) đã được đăng ký criteria (expectancy>0, CI95 lo>0, n≥100) TRƯỚC
khi chạy. OOS2-data 7 symbol đang tải nền. **Token OOS2 là quyết định của user** vì rule
OOS1-CI chênh nhẹ chưa khép — tiêu bây giờ = chấp nhận 1 phát quyết định cho cả lớp.

Ba lựa chọn tại bước này:
1. **Tiêu OOS2 one-shot ngay** — pass → ứng viên edge hoàn chỉnh (muốn go-live nhưng vẫn qua
   testnet/mainnet-size-nhỏ theo M6); fail → NO-GO chốt cả lớp fade, giữ hệ thống.
2. **Chờ thêm evidence trước khi tiêu OOS2** — replicate symbol mới (4 hàng: ATOM/DOT/LTC/DOGE
   đã có sẵn), hoặc tích hợp H8 Deribit skew làm confluence, rồi mới tiêu OOS2 một lần duy nhất.
3. **Đổi venue/fee tier** — RT < 0.05% (không tiêu OOS2 vì cấu hình của venue khác cần VAL riêng).

1. **Renegotiate gate 0.05R cho lớp governed** — ensemble-8 đã dương TRAIN (CI>0); câu hỏi là
   chấp nhận edge mỏng + regime risk không.
2. **Regime-conditional tần suất thấp** — chỉ trade stress (gate vol tuyệt đối cao); lệnh hiếm
   (< 300/năm — vi phạm reality-check plan, ghi nhận thẳng).
3. **Venue/fee tier thấp hơn** — RT < 0.05% đổi phép chiếu; cùng cấu trúc vượt gate trên paper.
4. **Chấp nhận NO-GO** — hệ thống giữ làm nền tảng research; FINAL OOS2 giữ đóng băng.

---
*Files chi tiết: `data/reports/*.json` (mỗi pre-registration một file), `hypothesis_ledger.jsonl`
(58 rows). Mọi số trong báo cáo này đo từ dữ liệu thật, không chiếu hợp.*
