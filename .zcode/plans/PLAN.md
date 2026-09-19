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
| Funding | Mặc định **8h (00/08/16 UTC)**; đo 500 kỳ gần nhất (≈166 ngày): **avg 0.0009%/kỳ, median 0.0017%, min −0.0388%, max 0.0100%**, 57% kỳ dương. ⚠️ **Interval không cố định** — Binance đổi tần suất settle (1h/2h/4h/8h) theo điều kiện thị trường (thông báo 2025-08); đọc động qua `fapi/v1/fundingInfo` (SOLUSDT vắng mặt trong response = đang mặc định 8h) | Gần như bằng 0 cho lệnh đóng trong ngày; vẫn đưa vào cost model; mọi mốc funding trong bot/blackout lấy theo interval hiện hành (mục 12, vòng 3) |
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
│   ├── features/   indicators.py, levels.py (round numbers 10 USDT, pivots UTC-00:00, zones), patterns.py, state.py,
│   │               context.py (BTC D1 trend, regime attribution), orderflow.py (taker imbalance/CVD từ klines, OI-context)
│   ├── strategies/ base.py, volman_breakout.py, brooks_h2l2.py, squeeze_pivot.py, cascade_fade.py (H1 — chỉ khi event-study pass)
│   ├── backtest/   engine.py (vectorbt wrapper), costs.py, monte_carlo.py, metrics.py, account.py
│   ├── research/   events.py (event-study, MFE/MAE, purged CV), hypotheses.py (ledger), splits.py, optimize.py,
│   │               report.py, alpha_decomp.py, robustness.py
│   └── live/       bot.py (ccxt/python-binance), risk_guard.py, health.py, journal.py, notify.py
├── scripts/        download_data.py, calibrate_costs.py, run_event_study.py, run_backtest.py, run_walkforward.py, run_alpha_decomp.py, run_live.py
├── tests/          (unit + chống lookahead + sanity fills + cost model)
├── data/           (parquet — .gitignore), reports/
```

Khác v1 của EURUSD: `mt5_client.py` → `binance_client.py`; timezone thống nhất **UTC** (crypto native, hết bẫy DST của Exness EET); thêm `funding.py` và `alpha_decomp.py` (tách gross/cost — v1 đã chứng minh đây là phép đo sống còn).

## 2. M0 — Môi trường (½ ngày)
- venv `.venv`: `pip install pyarrow pyyaml pytest loguru ccxt python-binance` + `pip install -e C:\Project\vectorbt` (repo có sẵn, v1.1.0) + `pip install vectorbt-rust` (Rust engine — xem 2b.2; nếu không có wheel cho nền tảng thì build: `cd C:\Project\vectorbt\rust && python -m maturin develop --release`).
- graphify cài 1 lần: `uv tool install graphifyy` (hoặc pipx) → `graphify install` (đăng ký skill `/graphify`); build graph cho repo này, dùng graph có sẵn của V1 (xem 2b.1).
- Smoke test M0 kèm 2 việc: (1) warm-up JIT numba 1 lần (40–110s — trả phí ở setup, không trả trong lúc research); (2) benchmark numba vs rust trên 1 grid cố định → chốt engine, `vbt.settings.save("config/vbt_settings.json")`.
- Verify API: `curl https://fapi.binance.com/fapi/v1/ping` từ máy (đã xác nhận hoạt động).
- `config/settings.yaml`: toàn bộ hằng số kể từ bảng mục 0 — không hardcode.

## 2b. Hai vũ khí tăng tốc sẵn có trên máy — dùng từ M0, xuyên suốt dự án

### 2b.1. graphify (`C:\Project\graphify`) — đọc repo nhanh, tiết kiệm token cho mọi phiên sau
Knowledge graph của repo: parse AST tree-sitter, 100% local, **0 chi phí API cho code**. Output `graphify-out/`: `GRAPH_REPORT.md` (god nodes, communities, kết nối bất ngờ), `graph.json` (graph đầy đủ để query), `graph.html` (trực quan). Đã chạy thử ở V1 (`solusdt-future/graphify-out/`: 641 nodes · 1968 edges · 33 communities) — god nodes chỉ ngay các abstraction lõi (CostConfig, StrategyRegistry, BacktestEngine…).

Quy trình chuẩn trong dự án này:
1. Build graph cho repo này: `/graphify .` → `graphify-out/`; **commit `GRAPH_REPORT.md`** (graph.json + cache thêm vào .gitignore nếu nặng) — phiên sau đọc 1 file MD thay vì re-đọc cả repo.
2. Sau mỗi lần sửa code: `graphify update .` (AST-only, không tốn API, vài giây) — graph không bao giờ stale; so commit hash trong GRAPH_REPORT.md với `git rev-parse HEAD` để biết graph có cũ không.
3. **Quy tắc cho mọi phiên AI (đưa vào AGENTS.md của repo):** câu hỏi kiến trúc → đọc `GRAPH_REPORT.md` trước; định tuyến code → `graphify explain "<tên>"` / `graphify path A B` / `graphify query "<câu hỏi>"` thay vì grep; không re-đọc file khi graph trả lời được.
4. Build/dùng graph cho 2 repo tham chiếu: `C:\Project\solusdt-future` (V1 — **đã có graph sẵn**, dùng ngay để định vị module cần mượn: health.py, conflict resolver, monte_carlo, calibration) và `C:\Project\vectorbt` (tìm API nhanh trong codebase lớn).

Hiệu quả: mỗi phiên mới tiết kiệm phần lớn token/công đọc repo; mượn code từ V1 định vị trong vài giây thay vì dò thủ công.

### 2b.2. vectorbt (`C:\Project\vectorbt`) — backtest nhanh hơn
Đã có guide tiếng Việt `C:\Project\vectorbt\HUONG_DAN_SU_DUNG.md` (mục 9 Settings, mục 10 Rust engine). Thứ tự tăng tốc:
1. **Numba cache (bắt buộc):** `vbt.settings["caching"]["enabled"]=True`; hàm signal viết module-level, chữ ký ổn định, không lambda/closure đổi liên tục → cache tái sử dụng; JIT warm-up 1 lần ở M0.
2. **Rust engine (tránh JIT overhead, nhanh hơn trên grid lớn):** `vbt.settings["engine"]="rust"` toàn cục hoặc `engine="rust"` theo từng gọi `from_signals`. Chốt engine từ benchmark M0 (2b ghi trên) — không đổi giữa chừng giữa các run để kết quả so sánh được.
3. **Broadcasting — luật cứng: không bao giờ loop Python theo tham số.** Cả grid chạy trong MỘT lần gọi `from_signals`: entries/exits là ma trận 2D (mỗi cột 1 tổ hợp), sinh qua broadcasting indicator + `vbt.Product`/`run_combs`, `group_by` để group kết quả theo tham số. 630k nến × hàng nghìn combo phải ra trong **phút**, không phải giờ.
4. **Bộ nhớ:** 630k bar × hàng trăm cột float64 có thể vượt RAM tiện dụng → bật chunking (`vbt.settings["array_wrapper"]`) khi OOM; giữ dữ liệu là numpy float64 (convert 1 lần từ parquet, pickle lại ma trận để không re-parse mỗi run).
5. `freq="5min"` (hoặc "15min") bắt buộc ở mọi Portfolio — chi tiết ở M4.

## 3. M1 — Dữ liệu Binance THẬT (1–2 ngày)
- **Lịch sử bulk**: monthly zip M5 từ `data.binance.vision/futures/um/monthly/klines/SOLUSDT/` (từ 2020-09 khi listing perp → ≈ 630k nến M5); REST `fapi/v1/klines` (1500/req) cho phần gần nhất. Kèm D1, H1, funding history (`fapi/v1/fundingRate` full), mark price.
- `quality.py`: dedupe, gap check, OHLC violation, chuẩn hóa UTC (mượn pattern quality-gate/quarantine của V1).
- `resample.py`: M5→H1→D1; **pivots theo cắt UTC 00:00** (crypto không có session close — quy ước này là chuẩn crypto thay 17:00 NY của FX); round numbers bước **10 USDT** (100/110/120…, siết 5 USDT khi giá < 50); ADR20.
- `calibrate_costs.py`: từ aggTrades + bookTicker 2 tháng gần nhất → bảng **slippage thực tế theo giờ, theo size và theo điều kiện volatility**; đối chiếu spread. **Bắt buộc có bảng slippage riêng cho thời điểm stop** — stop luôn kích hoạt lúc biến động mạnh nên slippage lúc stop ≠ slippage trung bình (V1 dùng `stop_slippage_multiplier 1.5`; V2 đo lại trên dữ liệu thật thay vì mượn con số).
- **Dữ liệu phái sinh core (nâng cấp từ phase-2, research 2026-09-20 — đã verify trực tiếp S3 có đủ cho SOLUSDT):** tải luôn từ đầu: `metrics/` (OI + top-trader long-short ratio, granular 5m), `liquidationSnapshot/` (**thanh lý thật** — notional/side/mốc thời gian), `bookDepth/` (độ sâu sổ lệnh lịch sử). Cả 3 phục vụ trực tiếp event-study H1/H4/H5 ở M2.6; vẫn chỉ được nhận làm filter qua ablation đúng trình tự (TRAIN chọn, VAL xác nhận, OOS chốt).
- **Funding interval động (research vòng 3):** lưu funding history kèm timestamp thực tế từng kỳ, không suy ra chu kỳ từ giả định 8h; `funding.py` đọc `fapi/v1/fundingInfo` định kỳ (SOLUSDT vắng mặt trong response = đang mặc định 8h). Mọi blackout quanh mốc funding (M2) và tính funding trong cost model theo interval hiện hành — Binance đã đổi tần suất settle nhiều symbol (1h/2h/4h/8h, thông báo 2025-08).

## 4. M2 — Features & bộ filter chung (2–3 ngày, có unit test)
- `indicators.py` giữ nguyên: EMA 13/20/25, MACD 12-26-9, ATR14, ADX14, RSI14, BB(20,2), KC(20,1.5), momentum 12.
- `patterns.py` giữ nguyên định nghĩa sách: inside bar, powerbar, doji, reversal bar, outside bar, ii/ioi, kangaroo tail, big shadow.
- `state.py`: always-in (Brooks), tight-TR (range N bar ≤ 0.30×ADR20 — **ADR crypto lớn hơn, filter này sẽ nới tay hơn FX, kiểm chứng phân phối trước**), barbwire, Impulse M30 (Elder).
- `levels.py`: magnet = round number gần nhất + pivot daily/weekly (UTC) + đỉnh/đáy swing + yesterday H/L. *(Nâng cao, phase 2: funding-rate cực đoan làm sentiment magnet.)*
- `context.py`: **BTC D1 trend** (EMA slope / ADX trên BTCUSDT) làm filter ứng viên trong grid, kèm **regime attribution** bull/bear/chop cho SOLUSDT — SOL là beta cao của BTC. Quy tắc an toàn từ V1: BTC-filter phải qua ablation đúng trình tự (không nhận feature chỉ vì cải thiện in-sample — V1 mục 9.5.7); regime chỉ dùng để **attribution kết quả**, không gate tín hiệu (bài học mean_reversion chết đói vì regime gate của V1).
- **Thay session filter FX bằng activity filter**: trade chỉ trong **12:00–21:00 UTC** (đo được ở mục 0), skip 10–11 UTC; blackout ±30' tin đỏ macro; blackout ±5' quanh mốc funding (mốc theo interval hiện hành — xem M1 funding interval động); toggle weekend (mặc định OFF cuối tuần, grid kiểm chứng). Flat cuối ngày → không giữ qua mốc funding nào.

## 4b. M2.5 — Lớp nghiên cứu edge: event-study TRƯỚC backtest (2–3 ngày) — trọng tâm "tìm edge thật sự"

Nguyên tắc meta: **sách FX cung cấp từ vựng mô hình (box, H2/L2, squeeze, magnet) — không cung cấp edge cho SOLUSDT.** V1 đã chứng minh setup mượn từ sách không tự chuyển đổi thành edge. Edge phải được *chứng minh trong vi cấu trúc của SOLUSDT*; setup sách chỉ là cách mô tả trigger. Đổi kỳ vọng: từ "xác nhận setup sách chạy được trên SOL" sang "tìm điều kiện nào trên SOL mà sau trigger-X giá có thiên lệch đo được".

- `events.py` — **event study cho mỗi giả thuyết nguyên tử** (vd: "inside bar đè sát round number, window 13–19 UTC"), chạy trước mọi backtest: phân phối forward-return có điều kiện tại +5m/+15m/+1h/+4h so với baseline vô điều kiện (excess + t-stat/bootstrap CI); **đường suy giảm edge theo thời gian** (signal sống 15 phút hay 4 tiếng → quyết định holding & M5/M15, không để grid quyết định); **phân phối MFE/MAE** sau trigger. Tiêu chí kill viết trước khi test: excess ≥ 0.05% tại +1h, t ≥ 2 trên TRAIN, giữ hướng trên VAL — không đạt → kill, không tốn backtest.
- **Derive SL/TP từ MFE/MAE** thay vì grid mù: SL nằm ở nơi đuôi MAE bắt đầu giết lệnh, TP ở nơi khối lượng MFE tập trung; grid ở M3/M5 chỉ fine-tune quanh giá trị đã derive (ít cell hơn → PBO thấp hơn).
- **Random-entry baseline (Tharp — có trong plan EURUSD gốc, bản chuyển đổi từng làm rơi):** simulate random-entry cùng luật thoát + cùng chi phí trên cùng dữ liệu; edge = expectancy(strategy) − expectancy(random) kèm bootstrap CI. Không vượt random → mọi "edge" chỉ là hình dáng của luật thoát → kill.
- `orderflow.py` — **nguồn edge riêng có của crypto mà sách FX không có:** taker imbalance + CVD lấy **trực tiếp từ trường taker-buy-volume trong klines** (đi kèm 630k nến M5, không cần tick data); OI × giá 4 góc phần tư + funding sign từ metrics (data.binance.vision, đã xác nhận có). Event-study từng cái làm **confirmation filter** cho S1/S3 — giả thuyết đầu tiên cần test: *break bar có taker-buy dominance → breakout thật; không có → trap*. Chỉ nhận qua ablation đúng trình tự.
- **Edge đo theo regime từ khâu event-study** (BTC-trend × ATR-percentile × funding-sign), không chỉ attribution sau backtest: edge chỉ tồn tại ở 1 regime → biến thành chiến thuật **regime-conditional** (ít lệnh hơn nhưng giả thuyết sạch hơn); edge âm ở mọi regime → kill sớm.
- `hypotheses.py` — **hypothesis ledger với kỷ luật falsification:** mỗi giả thuyết có ID + tiêu chí pass/fail viết TRƯỚC khi test + verdict kill/keep; **cap số giả thuyết mỗi segment dữ liệu** (research degrees of freedom — mỗi giả thuyết thêm là một lần xoay bánh multiple-testing); ghi lại cả giả thuyết chết (chống publication bias với chính mình).
- **Purged CV + embargo ≥ label horizon** cho mọi phép đo có forward-label: forward-return 4h trên M5 chồng lấn 48 bar → K-fold thường leak tương lai (walk-forward 3 tháng ở M5 an toàn vì cửa sổ rời nhau; event-study và grid thì bắt buộc purge).
- *(Phase 3 — chỉ khi có chiến thuật base gross-dương và mẫu ≥ 1000 event: **meta-labeling** — model phụ (order-flow, regime, funding, time-of-day) chỉ lọc nhận/bỏ tín hiệu, không dự đoán hướng.)*

## 4c. M2.6 — Menu giả thuyết edge có bằng chứng bên ngoài (research 2026-09-20) — nguồn edge không có trong sách

M2.5 cho **quy trình** kiểm định; mục này cho **danh mục giả thuyết đáng kiểm định** — mỗi cái có bằng chứng học thuật/thực chiến công khai (nguồn ở mục 12). Mỗi giả thuyết đi qua event-study đúng quy tắc M2.5 trước khi vào backtest. **Không giả định trước hướng** — literature có chỗ bất đồng (momentum vs reversal) thì để dữ liệu SOLUSDT quyết định.

- **H1 — Liquidation-cascade exhaustion fade (ứng viên S4):** literature ghi nhận crypto có intraday momentum VÀ reversal (Wen et al. 2022, cited 51+); liquidation cascade tạo overshoot rồi revert khi forced-flow cạn (case study cascade Oct-2025; SSRN 2025 "two-regime liquidity recovery"). **Nâng cấp dữ liệu 2026-09-20: `liquidationSnapshot/` có trên data.binance.vision cho SOLUSDT** → backtest bằng thanh lý THẬT (liquidation intensity = notional/phút theo chiều). Trigger cần test: thanh lý 1 chiều dồn dập (rolling intensity > percentile cao) + giá lập extreme → entry khi intensity **cạn** và bar đầu tiên KHÔNG lập extreme mới (overshoot-and-revert). Proxy (OI drop + volume spike) chỉ dùng cho đoạn lịch sử thiếu snapshot. Đây là bản sửa có cấu trúc cho `liquidity_sweep` của V1 (PF 0.92, bắt nhiễu vì sweep không có volume/OI confirmation). *Caveat dữ liệu (research vòng 3): liquidationSnapshot kế thừa sampling của stream `forceOrder` — chỉ 1 lệnh/symbol/1000ms (Binance docs) → cascade cường độ cao bị undercount; coi liquidation intensity là **proxy thứ hạng (percentile)**, không phải đếm tuyệt đối; OI-drop là cross-check bắt buộc.*
- **H2 — BTC→SOL lead-lag (filter ưu tiên):** BTC leads altcoin ở intraday (Sifat et al. 2019, cited 105; tick-level 2023); nhưng có nghiên cứu thấy cross-predictability âm kiểu "seesaw" (Jia 2023) → event-study **cả hai hướng**: BTC jump ±X% ở 5–15m → SOL tiếp diễn hay đảo ngược? Đầu ra là filter cho S2/S3 (BTC-momentum/BTC-reversal filter ở horizon 5–15m, khác filter BTC D1 trend đã có ở context.py).
- **H3 — Seasonality cơ học theo giờ/mốc nến:** quarter-hour effect — opening order imbalance dự báo 4–12h (arXiv); turn-of-candle effect — return dương dồn ở biên nến 15m (Shanaev 2023); hour-of-day pattern (BTC: 22:00 UTC). Event-study: ma trận giờ×ngày forward-return trên SOLUSDT, hiệu ứng biên nến 15/60m. Chi tiết hoá quanh mốc funding: ±60 phút quanh 00/08/16 UTC **điều kiện theo percentile funding rate** (funding cao → pre-funding drift hay post-funding reversal?) — arXiv 2024 ghi nhận funding rate biến động mạnh hơn ngay sau mốc funding. Rẻ nhất trong menu — chạy trong phút — và là edge về **cơ chế thị trường** (algorithmic flow, liquidity cycle) chứ không phải chart pattern.
- **H4 — Order-flow imbalance dạng liên tục (nâng cấp filter taker-imbalance hiện có):** OFI là driver ngắn hạn mạnh nhất theo literature (Vafin 2026 SSRN; Anastasopoulos 2024: order flow dự báo crypto OOS, lấn át fundamentals). Cảnh báo practitioner: sức dự báo **nhạy với cách dựng** (horizon, chuẩn hoá) → event-study nhiều biến thể OFI (cộng dồn 5m/15m, z-score theo rolling vol, lag khác nhau), không chọn trước một biến thể. Nâng cấp dữ liệu: `bookDepth/` lịch sử có trên data.binance.vision → biến thể OFI từ **độ sâu sổ lệnh** (imbalance top-N level) cũng backtest được, không chỉ taker-flow.
- **H5 — Premium/basis perp-vs-index làm context:** premium index của Binance (miễn phí `fapi/v1/premiumIndex`, history có trên data.binance.vision) = phiên bản tức thời của funding; premium cực đoan → crowding/mắt xích yếu. Làm context/confirmation cho H1–H4; event-study trước.
- **H6 — Track B: Funding-carry delta-neutral (song song Track A scalping):** bằng chứng học thuật **mạnh nhất** trong menu — "Crypto Carry" (Schmeling et al., Management Science 2026); nghiên cứu funding arb báo lợi nhuận tới 115.9%/6 tháng (Werapun et al. 2025). Bản chất khác hẳn scalping: rất ít lệnh, mỗi lệnh "R" lớn, **chịu phí tốt** (chi phí vào/ra ~0.24% RT qua spot+perp amortise khi giữ nhiều ngày) — đúng thứ mà V1 chết vì thiếu. Cấu trúc: long spot SOL + short perp khi funding > ngưỡng cao (percentile lịch sử), exit khi funding về median. Thẳng thắn về rủi ro: funding 166 ngày gần đây avg chỉ 0.0009%/8h → carry chỉ trả cao trong regime mania (hiếm nhưng lớn) → event-study **full funding history từ 2020** đo tần suất/độ dài/thu nhập mỗi regime trước khi làm gì khác. Yêu cầu hạ tầng: spot leg, giữ lệnh qua mốc funding (**ngoại lệ duy nhất** cho luật flat-trong-ngày, áp dụng riêng Track B, risk margin riêng).

- **H7 — Risk-managed momentum / vol-targeting overlay (lớp TSMOM khung lớn):** research 2025: vol-scaled momentum tăng Sharpe đáng kể (Yang 2025); TSMOM crypto đã được chứng minh (Borgards 2021, cited 32; Grobys 2025 về tail risk & vol-managed momentum). Hai ứng dụng cho SOL intraday: (a) **regime gate** — SOL D1 momentum (20–90 ngày) làm bias hướng cho S2 (pullback chỉ long khi TSMOM dương); (b) **vol-targeted sizing overlay** — scale risk 1% theo percentile ATR (risk × median-ATR/ATR-hiện-tại, có cap). Cả hai qua ablation đúng trình tự; không nhận nếu chỉ giúp IS.
- **H8 — Options skew / risk-reversal làm context D1 (nguồn ngoài Binance):** RR spread 25Δ trên Deribit **dự báo daily BTC returns ở mức ý nghĩa 1%** (Neo 2026, SMU); DVOL = chỉ số IV của Deribit. Deribit API public miễn phí (có SOL options). Ứng dụng: context filter hàng ngày cho Track A (RR cực đoan put → chế độ nào cho ngày kế? — test theo dữ liệu, không giả định hướng). Rẻ: ~1 request/ngày.

**Đã đánh giá & HOÃN (ghi lại để tiết kiệm công lần sau):** cross-exchange lead-lag (Bybit/OKX → Binance) — Albers 2021 (cited 20) chứng minh **Binance là sàn DẪN ĐẦU price discovery**, Bybit/BitMEX lag theo → tín hiệu từ sàn khác đến SAU Binance, vô dụng cho bot resident trên Binance; Zhivkov 2026 cho thấy hierarchy động hơn nhưng chưa đủ làm giả thuyết chính. Revisit chỉ khi tương lai trade đa sàn.

### 4c.1 — Nguồn giả thuyết từ tạp chí TA (khảo sát 2026-09-20) — "publications feed" cho hypothesis ledger

Ba tạp chí được user chỉ định; xếp hạng theo giá trị kỳ vọng cho edge codable. **Uy tín tạp chí không miễn trừ gate** — mọi giả thuyết rút ra vẫn đi qua event-study M2.5 như mọi giả thuyết khác:

| Nguồn | Giá trị | Khai thác được gì | Truy cập |
|---|---|---|---|
| **CMT Association — Journal of Technical Analysis (JOTA)** | **CAO** (peer-reviewed) | ~500 bài TA đã peer-review qua 43+ năm (71+ issues) — mỏ kiểm định định lượng của TA: reversal, seasonality, indicator validation trên futures. Trích bài liên quan futures/crypto/reversal thành giả thuyết M2.5 kèm citation | PDF miễn phí, vd [JOTA 2020 Issue 71](https://cmtassociation.org/wp-content/uploads/2020/03/JOTA-2020-Web-Version.pdf), [trang tạp chí](https://cmtassociation.org/education/publications/journal-of-technical-analysis) |
| **TASC — traders.com** | **CAO về số lượng codable** | Cột **Traders' Tips** hằng tháng: chiến thuật featured của mỗi số được code sẵn (TradeStation/Pine/MetaStock/…) — mỏ giả thuyết codable liên tục từ 1982, mức ~12 hệ thống/năm | traders.com chặn bot (403) → cần subscription để đọc bài; **lối đi miễn phí**: archive code Traders' Tips trên metastock.com |
| **Traders World (Halliker's, từ 1978)** | THẤP — chỉ subset cycle | Chủ yếu Gann/Elliott/astro, không peer-review, không code archive. Chỉ phần **time-cycle/ngày lịch** codable được → test như calendar event-study (rẻ, máy móc, vẫn qua gate) | tradersworld.com; issue cũ trên Scribd/Yumpu |

**Quy trình feed (ritual mỗi quý, ghi vào `hypotheses.py` ledger):** (1) JOTA — tải issue mới, lọc bài futures/crypto/reversal/seasonality → giả thuyết kèm citation; (2) TASC — duyệt Traders' Tips 12 tháng gần nhất, lọc hệ thống phù hợp futures/crypto intraday → giả thuyết (bỏ những gì chỉ hợp daily equity); (3) Traders World — bỏ qua trừ khi có time-cycle cụ thể test được. **Cảnh báo publication bias:** bài TASC đăng winner của tác giả → mọi backtest trong bài chỉ là *claim*; replication trên dữ liệu SOLUSDT qua event-study là phán quan duy nhất — DSR/multiple-testing discipline ở M5 xử lý phần còn lại.

## 5. M3 — Ba chiến thuật ứng viên (3–5 ngày) — giữ nguyên cấu trúc sách, tham số đến từ M2.5, re-anchor khoảng cách theo bảng 0.1

Chung: risk 1% (0.5 USDT)/lệnh, Percent-Risk sizing (Tharp), SL = cực trị signal bar ± offset (5–10 ticks), cap SL theo bảng 0.1, TP 2R, một vị thế, đóng trong ngày. **Mỗi chiến thuật phải sinh ≥ 200 tín hiệu trong TRAIN — chiến thuật "đói tín hiệu" như mean_reversion của V1 (2 lệnh/540 ngày) bị loại ngay, không nới ngưỡng tùy ý.** Khi ≥2 chiến thuật ra tín hiệu cùng nến: **conflict resolver** bắt buộc — cùng hướng thì nhận 1 vị thế tốt nhất (rank theo expectancy trên VALIDATION), ngược hướng thì skip cả hai; mượn module từ V1 (portfolio/conflict resolver).

- **S1 — Volman Breakout**: box tight ≥3 bar đè sát barrier (round number/pivot/box extreme); trigger inside bar hoặc powerbar+inside combi; **2 biến thể entry đưa vào grid**: (a) stop-market 5–10 ticks qua cực trị (taker, nguyên bản sách), (b) **entry-retest** — chờ giá break rồi đặt limit maker ở mức trigger kèm xác nhận giữ mặt giá (con đường maker khả dĩ cho breakout; đo non-fill rate, chấp nhận miss một phần tín hiệu). Filter 25 EMA slope, không adverse magnet 0.15% tới TP, không tight-TR, không entry từ xa.
- **S2 — Brooks H2/L2 Pullback**: always-in M5 (grid thêm biến thể always-in tính trên H1, entry M5); H2/L2 + reversal bar; pullback ≥40% chạm EMA20; entry 1 offset qua signal bar, kèm biến thể retest như S1; TP 2R (nửa 1R + BE phase 2); cấm tight-TR/barbwire; second entry.
- **S3 — TTM Squeeze + Pivot**: squeeze ON/OFF như Carter; confluence pivot/round ≤ 0.10–0.15%; entry market (taker — tính phí); SL max(0.25%, 2×ATR5m); exit momentum roll-over hoặc 2R.
- Meta-parameter: **M5 vs M15** cho cả 3 chiến thuật (SOL 5m nhiễu hơn EURUSD; V1 chạy 15m) — quyết định qua funnel, không đoán.
- **Tham số đến từ M2.5, không grid mù:** SL/TP/offset derive từ MFE/MAE + đường suy giảm edge của event study; grid chỉ fine-tune quanh đó. Filter order-flow (taker imbalance/CVD), OI-context và regime-conditional từ M2.5 là filter ứng viên chung của cả 3 chiến thuật — chỉ nhận qua ablation VALIDATION.
- **Ưu tiên phát triển maker-first (thứ tự thiết kế bắt buộc):** (1) mỗi chiến thuật được phát triển thử entry **post-only limit** tại/qua cực trị trigger trước; (2) chỉ dùng **stop-market taker** khi cấu trúc chiến thuật bắt buộc (S1 breakout momentum). S2/S3 vốn entry limit/pullback → maker-friendly tự nhiên; S1 bản chất taker → phải tự chứng minh gross đủ lớn để trả phí taker. Funnel báo cáo thêm **maker-share** (tỷ lệ lệnh khớp maker) và fill-rate post-only cho từng chiến thuật, song song với PnL. *Lưu ý cơ chế với S1: post-only đặt ngay tại cực trị chỉ khớp khi giá quay lại chạm (adverse selection có chủ đích) — biến thể maker khả dĩ cho breakout là entry-retest (định nghĩa ở S1).*

## 6. M4 — Backtest engine vectorbt (2 ngày)
- `engine.py` wrap `Portfolio.from_signals` như plan gốc: intrabar OHLC fills, `freq="5min"` (hoặc 15min nếu meta chọn M15). **Same-bar SL+TP chạy 2 bound**: pessimistic SL-first (mặc định báo cáo chính) + optimistic TP-first; nếu chiến thuật chỉ lãi ở bound TP-first → fragile, loại. **Fill rule cho lệnh limit (maker-base): chỉ khớp khi giá đi XUYÊN QUA mức limit (trade-through), không khớp khi chỉ chạm** — touch-fill mặc định của vectorbt lạc quan cho maker; nếu custom fill-rule không khả thi, chạy cả hai chế độ và báo cáo chênh lệch làm sensitivity bắt buộc.
- `costs.py` — **mọi phí theo giả định BNB: maker 0.018% / taker 0.045%**; 2 kịch bản, **maker-base là kịch bản chính** (hướng phát triển maker-first), taker-worst chỉ là stress:
  - `maker-base` (**chính**): entry post-only limit tại trigger (mô hình **non-fill + adverse selection** — bài học V1 mục 9.5.5), TP limit maker 0.018%, SL taker 0.045% + slippage. RT kỳ vọng ≈ 0.035–0.055%.
  - `taker-worst` (stress): entry stop-market taker 0.045%, SL stop-market taker + **slippage theo bảng điều kiện-vol tại thời điểm stop** (multiplier đo được từ aggTrades, tham chiếu hệ số 1.5 của V1), TP limit maker 0.018%. RT ≈ 0.09–0.11%.
  - Funding: tính khi vị thế băng qua 00/08/16 UTC (mặc định 0 vì flat trong ngày).
  - Sensitivity ±50% phí + cost-shock Monte Carlo (mượn từ V1); ±50% quanh mức BNB bao trùm cả trường hợp **hết BNB → revert phí gốc 0.02%/0.05% (+11%)**.
- **Cost theo thanh khoản lịch sử (research vòng 3):** bảng slippage/spread đo từ 2 tháng gần nhất KHÔNG đại diện cho 2020–2021 (SOL perp khi đó mỏng hơn nhiều bậc) → scale slippage theo volume lịch sử từng năm (tỷ lệ volume_năm/volume_hiện_tại), hoặc gắn cờ kết quả trước 2022 là "cost-uncertainty cao"; phán quyết edge dựa trên walk-forward đoạn 2022→2026 và FINAL OOS.
- `monte_carlo.py` (mượn khung V1): **shuffle thứ tự lệnh + percentile drawdown + max losing streak + cost-shock đơn điệu** — với vốn $50, drawdown biên quan trọng hơn point estimate.
- `robustness.py`: láng giềng tham số quanh optimum, leave-one-out chiến thuật, detector lag +1/+2 nến (V1 có đủ khung để tham chiếu); **kiểm soát multiple-testing: grid > ~200 tổ hợp thì chạy thêm PBO/CSCV** (rẻ nhờ vectorbt broadcasting).
- `account.py`: equity $50 USDT; qty = risk / SL_distance, làm tròn xuống 0.01 SOL; **check minNotional ≥ 5 USDT, qty ≥ 0.01 SOL, đòn bẩy hiệu dụng ≤ 5× isolated**. Ví dụ: risk 0.5 USDT, SL 0.7 USDT → 0.71 SOL ≈ 79 USDT notional ≈ 1.6× — nằm gọn trong cap, và SL (−0.7%) luôn kích hoạt trước thanh lý (5× isolated → liquidation ≈ −19%).
- `metrics.py`: như plan gốc (expectancy > 0.05R sau chi phí, SQN ≥ 2.0, PF ≥ 1.3, ≥ 100 trades/segment, maxDD ≤ 25%) **+ phân rã gross/cost/net theo chiến thuật (alpha decomposition — bắt buộc từ V1) + attribution theo regime (bull/bear/chop) và hướng BTC trend** — chiến thuật chỉ pass funnel nếu không sống nhờ đúng một regime.

## 7. M5 — Chia dữ liệu & Funnel (3–4 ngày) — chống overfitting (SOL perp từ 2020-09, dời mốc tương ứng)
1. **TRAIN** 2020-10 → 2023-06 — nghiên cứu, grid (SL 0.4–1.2%, TP 1.5–3R, offset {5,10,15} ticks, EMA 18–30, M5/M15, weekend toggle).
2. **VALIDATION** 2023-07 → 2024-06 — chọn params/chiến thuật.
3. **TEST OOS#1** 2024-07 → 2025-08 — chỉ chạy khi đã chốt.
4. **WALK-FORWARD**: train 12 tháng / test 3 tháng, cuốn 2020→2025; stitch equity OOS.
5. **FINAL OOS#2** 2025-09 → 2026-08 — không đụng tới đến lúc quyết định go-live.

Cổng sống sót giữ nguyên từ plan gốc (Tharp/Elder) **+ gate riêng của V2**:
- Gross expectancy (zero-cost, cùng tập lệnh) phải **dương** trước khi nói gì đến phí — nếu gross âm thì sửa hypothesis, không dùng maker để cứu (V1 mục 9.5.3).
- Expectancy sau chi phí **trong kịch bản maker-base (kịch bản chính)** > 0.05R; taker-worst được báo cáo làm stress, chấp nhận âm nhẹ nhưng phải ghi rõ điều kiện sống.
- **Chỉ lãi ở bound TP-first (same-bar) → loại.** Mỗi cửa sổ walk-forward phải có **≥ 20 lệnh OOS** để có giá trị thống kê; attribution regime phải cho thấy kết quả không dồn vào một regime duy nhất.
- **Reality-check cỡ mẫu (research vòng 3):** chứng minh expectancy 0.05R với σ ≈ 1R cần ≈ 1,500+ lệnh để đạt t ≈ 2 — mẫu ≥ 200 trong TRAIN chỉ đủ LOẠI chiến thuật tệ, không đủ CHỨNG MINH edge. Do đó: mọi quyết định go/no-go theo **bootstrap CI của expectancy** (không theo điểm số); tính trước số lệnh kỳ vọng/năm của ứng viên cuối — nếu < 300 lệnh/năm thì phải gộp chiến thuật cùng lớp hoặc nâng TF một cách rõ ràng; lệnh testnet/mainnet-size-nhỏ được cộng dồn vào bằng chứng (mỗi lệnh live là một mẫu OOS thật).
- **Random-entry gate:** expectancy của chiến thuật phải vượt random-entry cùng luật thoát + cùng chi phí (simulate trên cùng dữ liệu), bootstrap CI không chứa 0.
- **Thống kê nâng cấp (research 2026-09-20):** báo cáo **DSR (Deflated Sharpe Ratio — Bailey & López de Prado)** cạnh mọi Sharpe/PF của ứng viên sống sót (sửa bias chọn-lọc + non-normality); **CPCV (Combinatorial Purged CV)** làm validation chính cho 1–2 ứng viên cuối — Arian et al. 2024 chứng minh CPCV vượt walk-forward trong chống overfitting (walk-forward giữ để stitch equity OOS); event-study dùng **moving-block bootstrap** (return crypto fat-tailed, không iid — bootstrap thường sai).
- **Pre-registration:** tiêu chí pass/fail của FINAL OOS#2 viết thành văn **trước khi** chạy OOS lần đầu — không chỉnh tiêu chí sau khi thấy kết quả.
- Baseline V1 (trend_pullback zero-cost +0.12R/lệnh, PF 1.014) làm **negative control tham chiếu**.

## 8. M6 — Live Bot Binance (3–4 ngày + demo 4 tuần)
- `bot.py`: dậy đúng nến M5 đóng (+2s) qua websocket kline hoặc poll REST; gọi **cùng module signal của backtest**; `order_send` qua ccxt/python-binance với: **one-way mode, isolated, leverage ≤ 5×, SL/TP là order giảm chỉ thị (reduceOnly)**, magic qua `newClientOrderId`.
- **Bracket không có OCO trên Binance futures**: mỗi vị thế = 2 lệnh reduceOnly (TP limit + SL stop-market) + logic **huỷ lệnh còn lại ngay khi một bên khớp** (userDataStream / poll position), xử lý partial fill, state persistence qua restart (idempotent — restart không đặt trùng lệnh).
- `ops/health.py` (mang nguyên từ V1): HealthMonitor (clock skew, staleness dữ liệu, error streak) + CircuitBreaker CLOSED/OPEN/HALF_OPEN — ngắt tự động khi API bất ổn thay vì retry mù.
- `risk_guard.py` — luật cứng (giữ nguyên plan gốc + bổ sung Binance): không lệnh thiếu SL; stop chỉ siết về BE; 3 thua hoặc −3% ngày → dừng ngày; −6% tuần → dừng tuần; **loss-streak cooldown phải tự reset theo thời gian (bug đóng băng vĩnh viễn của V1)**; blackout tin; **margin-ratio alert + kill-switch trước khi chạm thanh lý** (dư địa ≥ 10× khoảng cách SL); API key chỉ Futures, không rút tiền, IP whitelist.
- **Live kill-switch định lượng:** sau ≥ 50 lệnh live thật, nếu expectancy < 50% backtest hoặc PF < 1.0 → dừng, quay lại research (không "chờ hồi").
- **BNB trả phí (giả định toàn plan)**: bật "Use BNB for Fees" khi setup tài khoản Futures; `risk_guard.py` theo dõi số dư BNB ví Futures — dưới ngưỡng tối thiểu (≈ 2 tuần phí dự kiến) → cảnh báo qua `notify.py`; hết BNB → phí revert 0.02%/0.05% (mất ưu đãi −10%) → flag vào `journal.py` vì mọi giả định cost model lệch đi. Funding fee **không** giảm BNB.
- Vận hành: reconnect, restart rollover, `journal.py` đối chiếu backtest↔live.
- **Lộ trình go-live tách 2 loại bằng chứng:** (1) **Testnet ≥ 4 tuần** — chỉ nghiệm thu *vận hành* (API, reconnect, bracket, risk_guard, restart); **fill testnet không dùng để đối chiếu cost model** vì sổ lệnh testnet là giả. (2) **Mainnet size nhỏ 1–2 tuần** — lệnh 0.01–0.05 SOL thật + log bookTicker/aggTrades read-only → so fills/spread/slippage với giả định backtest (lệch > 30% → hiệu chỉnh cost model; fill-rate post-only mục tiêu ≥ 60%) → mới bật live $50 margin, leverage 5× isolated cap. VPS chạy 24/7.

## 9. Rủi ro nhận diện & biện pháp
- **Chi phí taker giết edge** (bằng chứng V1) → **maker-first là hướng phát triển ưu tiên số 1** (entry post-only trước, taker chỉ khi cấu trúc bắt buộc) + gate gross-trước-phí + alpha decomposition bắt buộc.
- **Hết BNB / quên bật "Use BNB for Fees"** → phí revert 0.02%/0.05% (mất ưu đãi −10%, taker RT lên ~0.10–0.12%) → `risk_guard.py` theo dõi số dư BNB; sensitivity ±50% đã bao trùm trường hợp này.
- Post-only limit có thể không khớp (miss tín hiệu) và khớp nhiều hơn khi breakout thất bại (adverse selection) → mô hình non-fill + adverse selection; đo fill-rate trên **mainnet size nhỏ**, không phải testnet (mục tiêu ≥ 60%).
- Slippage lúc stop luôn xấu hơn trung bình (stop kích hoạt đúng lúc biến động mạnh) → bảng slippage theo điều kiện vol + multiplier stress trong cost model.
- SOL 5m ADR/ATR khác EURUSD → mọi khoảng cách qua grid TRAIN, không hardcode theo pip.
- Funding cực đoan (min đo được −0.039%) → flat trong ngày loại trừ gần hết; vẫn mô hình hóa.
- Price action sách khó codify 100% → subset máy móc, rating ≤ 3, cross-check nguồn (giữ nguyên plan gốc).

## 10. Thứ tự & thời gian (≈ 3 tuần làm việc)
M0 (0.5d) → M1 (1.5d) → M2 (2.5d) → **M2.5 event-study + M2.6 menu edge có bằng chứng (3d)** → M3 (4d) → M4 (2d) → M5 (3.5d) → M6 bot (4d) → testnet 4 tuần → mainnet size nhỏ 1–2 tuần → go-live $50.
Cổng go/no-go: (0) sau M2.5/M2.6 — mỗi chiến thuật phải có ≥ 1 giả thuyết event-study pass (excess dương, t ≥ 2 trên TRAIN, giữ hướng trên VAL) mới được vào backtest; ưu tiên giả thuyết có bằng chứng bên ngoài (M2.6) vì xác suất edge thật cao hơn; (1) sau funnel M5 — cả gross lẫn net maker-base phải pass; (2) sau testnet — vận hành sạch; sau mainnet size nhỏ — fills khớp giả định (lệch ≤ 30%); (3) trước bật tiền thật đầy đủ.

## 11. Luật cứng rút từ V1 (không được vi phạm)
1. **Maker-first là điều kiện sống còn VÀ hướng phát triển ưu tiên, không phải tối ưu hóa.** V1 chết vì taker RT ≈ 15–25% R. Mọi chiến thuật phát triển theo thứ tự: entry post-only trước, stop-market taker chỉ khi cấu trúc bắt buộc.
2. Gross alpha phải dương ở zero-cost trên cùng tập lệnh trước mọi thí nghiệm execution.
3. Chiến thuật đói tín hiệu (mẫu < 200 trong TRAIN) bị loại, không nới ngưỡng.
4. Mọi run phải ghi `run_id` + config hash + manifest; holdout cuối kỳ đóng băng.
5. Loss-streak cooldown tự reset theo thời gian; không bao giờ đóng băng vĩnh viễn.
6. Chi phí đo từ aggTrades thật, không giả định; sensitivity ±50% bắt buộc.
7. **Toàn bộ plan tính phí theo BNB** (maker 0.018% / taker 0.045%): phải bật "Use BNB for Fees" và giữ đủ số dư BNB trên tài khoản thật; hết BNB → phí +11% so với giả định, phải re-check cost model. Funding fee không giảm BNB.
8. Chiến thuật chỉ lãi khi giả định TP-first (same-bar) hoặc chỉ nhờ maker-fill ở entry stop-order → không đáng tin, loại.
9. Testnet chứng minh plumbing, mainnet size nhỏ chứng minh fill — không bao giờ dùng fill testnet để hiệu chỉnh cost model.
10. Live ≥ 50 lệnh mà expectancy < 50% backtest → dừng về research; không nới lỏng để "chờ hồi".
11. Conflict resolver phải quyết định được mọi cặp tín hiệu xung đột cùng nến; không bao giờ có 2 vị thế ngược hướng cùng lúc.
12. Không có backtest nào chạy trước khi giả thuyết của nó pass event-study (excess dương, t ≥ 2 trên TRAIN, giữ hướng trên VAL — M2.5).
13. Hypothesis ledger là tài sản: cap số giả thuyết mỗi segment dữ liệu, ghi lại cả giả thuyết chết; "tinh chỉnh đến khi lãi" = vi phạm.
14. Grid backtest không bao giờ loop Python theo tham số — 1 lần `from_signals` broadcast (2b.2); engine (numba/rust) chốt từ benchmark M0, không đổi giữa chừng.
15. Phiên AI làm việc trong repo này phải đi qua graphify (2b.1) trước khi đọc file thô; sau khi sửa code phải `graphify update .`.
16. Mọi giả thuyết vào backtest phải có (a) bằng chứng bên ngoài (mục 12) HOẶC observation riêng của dự án, và (b) event-study pass theo M2.5. Không ưu tiên setup sách chỉ vì "sách nói vậy" — M2.6 có các edge class với bằng chứng mạnh hơn (đặc biệt H6 carry, H1 cascade fade); ưu tiên tối thượng của dự án là tìm được edge, không phải chứng minh sách đúng.
17. **Funding interval đọc động, không hardcode 8h** — `fapi/v1/fundingInfo` (SOLUSDT vắng mặt = 8h); Binance đã/có thể đổi tần suất settle 1h/2h/4h/8h; bot nạp interval khi start và theo dõi thông báo thay đổi; mọi blackout quanh mốc funding theo interval hiện hành.

## 12. Nguồn tham khảo cho M2.6 (research 2026-09-20)
- **H6 carry:** Crypto Carry — Schmeling, Schrimpf & Todorov, *Management Science*: [pubsonline.informs.org](https://pubsonline.informs.org); Funding-rate arbitrage risk/return — Werapun et al. 2025: [sciencedirect.com](https://www.sciencedirect.com); Perpetual Futures Pricing — Ackerer et al. 2024 (Wharton): [finance.wharton.upenn.edu](https://finance.wharton.upenn.edu)
- **H1 cascade/reversal:** Intraday Return Predictability in Crypto — Wen et al. 2022 (momentum + reversal); Two-Regime Liquidity Recovery After a Perpetual Futures Liquidation Cascade (SSRN 2025); Anatomy of the Oct 10–11 2025 Cascade (ResearchGate 2025)
- **H2 lead-lag:** Lead-Lag Between Bitcoin and Ethereum — Sifat et al. 2019 (cited 105); A Seesaw Effect in the Cryptocurrency Market — Jia 2023: [sciencedirect.com](https://www.sciencedirect.com); tick-level lead-lag (2023)
- **H3 seasonality:** The Quarter-Hour Effect: Periodic Algorithmic Trading — [arxiv.org](https://arxiv.org); Turn-of-the-Candle Effect in Bitcoin Returns — Shanaev 2023; Seasonality in the Cross-Section of Crypto Returns — Long 2020 (cited 64)
- **H4 order flow:** Order-Flow Imbalance and Short-Horizon Return Predictability — Vafin 2026: [papers.ssrn.com](https://papers.ssrn.com); Order Flow and Cryptocurrency Returns — Anastasopoulos 2024: [sciencedirect.com](https://www.sciencedirect.com)
- **Phương pháp:** Backtest Overfitting in the ML Era (CPCV > walk-forward) — Arian, Norouzi & Seco 2024: [papers.ssrn.com](https://papers.ssrn.com); Deflated Sharpe Ratio — Bailey & López de Prado (*JPM*); [github.com/eslazarev/purged-cross-validation](https://github.com/eslazarev/purged-cross-validation) (implementation tham chiếu)
- **Tạp chí TA (khảo sát 2026-09-20, quy trình khai thác ở 4c.1):** Journal of Technical Analysis — CMT Association (peer-review, PDF miễn phí): [cmtassociation.org/education/publications/journal-of-technical-analysis](https://cmtassociation.org/education/publications/journal-of-technical-analysis); TASC / Traders' Tips: [traders.com](https://traders.com) + archive code miễn phí trên [metastock.com](https://www.metastock.com); Traders World (Gann/cycles — giá trị thấp, chỉ subset time-cycle): [tradersworld.com](https://www.tradersworld.com)
- **Vòng research 2 (2026-09-20):** Risk-managed momentum tăng Sharpe — Yang 2025: [sciencedirect.com](https://www.sciencedirect.com); Dynamic TSMOM crypto — Borgards 2021 (cited 32); tail/vol-managed momentum — Grobys 2025; Bitcoin Options Risk-Reversal Predictability — Neo 2026: [ink.library.smu.edu.sg](https://ink.library.smu.edu.sg); 25Δ RR thực chiến — Deribit Insights: [insights.deribit.com](https://insights.deribit.com); Fundamentals of Perpetual Futures — arXiv 2024 (funding biến động mạnh hơn sau mốc): [arxiv.org](https://arxiv.org); cross-exchange price discovery — Albers 2021 (Binance leads): [tandfonline.com](https://www.tandfonline.com); Zhivkov 2026: [mdpi.com](https://www.mdpi.com). **Dữ liệu verify trực tiếp trên data.binance.vision cho SOLUSDT (S3, 2026-09-20): `liquidationSnapshot/`, `bookDepth/`, `metrics/`.**
- **Vòng research 3 (2026-09-20):** Binance cập nhật tần suất settle funding (1h/2h/4h/8h, thông báo 2025-08): [binance.com](https://www.binance.com); endpoint `fapi/v1/fundingInfo` — chỉ liệt kê symbol non-default, vắng mặt = mặc định 8h; giới hạn stream thanh lý `!forceOrder@arr` — chỉ 1 lệnh/symbol/1000ms: [developers.binance.com](https://developers.binance.com); Probability of Backtest Overfitting (CSCV) — Bailey, Borwein, López de Prado & Zhu 2015: [papers.ssrn.com](https://papers.ssrn.com)
