# Roadmap: từ mock end-to-end → app hoàn chỉnh

Trạng thái hiện tại (đã xong, commit `1825b99`): Phases 1–5 của plan gốc — core thuần pandas
(indicators/filters/strategies), engine (main_loop evaluate-all-decide-after, order_engine
fill-at-next-open, runner), mock synthetic feed, SQLite (counters DERIVED, config versioned),
FastAPI REST, React dashboard 4 trang. Toàn bộ chạy trên **dữ liệu mock, 1 symbol (EURUSD), paper**.

Nguồn chân lý: `docs/spec_v1_2.md`. Mọi quyết định & sai lệch: `docs/decisions.md` (D1–D11,
C1–C12, 14 deviations). **Ràng buộc xuyên suốt: không tự thêm chiến lược/bộ lọc ngoài spec.**

## Các plan (mỗi file giao cho Sonnet thực hiện độc lập)

| # | File | Nội dung | Phụ thuộc |
|---|---|---|---|
| 01 | [01-stabilize.md](01-stabilize.md) | Commit fix thread-safety, trả nợ kỹ thuật (lot-at-fill, path-priority), A/B filter harness, CI | — |
| 02 | [02-real-data.md](02-real-data.md) | Import CSV lịch sử thật (giá + DXY), chi phí giao dịch §10 | 01 |
| 03 | [03-backtest-analytics.md](03-backtest-analytics.md) | Metrics backtest, run registry, trang Report, chart nến + markers | 02 |
| 04 | [04-multi-symbol.md](04-multi-symbol.md) | Đa symbol, `list[OpenTrade]`, MAX_CONCURRENT_TRADES thật, profile per-symbol | 01 (nên sau 03) |
| 05 | [05-stock-vn.md](05-stock-vn.md) | Profile chứng khoán VN (CASH + VN30F), ALLOW_SHORT, T+2.5, đáo hạn | 04 |
| 06 | [06-news-calendar.md](06-news-calendar.md) | Nguồn dữ liệu cho filter `news` (blackout windows) | 02 |
| 07 | [07-live-paper.md](07-live-paper.md) | Chạy live paper-trading: feed thời gian thực, recovery, Telegram | 02, 03 |
| 08 | [08-broker-execution.md](08-broker-execution.md) | (Tuỳ chọn) đặt lệnh thật qua broker — chỉ sau khi user chốt | 07 |
| 09 | [09-ops-polish.md](09-ops-polish.md) | Docker, auth token, logging, frontend tests | 03 (bất kỳ lúc nào sau đó) |
| 10 | [10-forex.md](10-forex.md) | (Nâng cao) Forex: data + venue — đề xuất OANDA v20, không cần Windows/MT5 | 07 (08 nếu lệnh thật) |
| 11 | [11-optimization.md](11-optimization.md) | (Nâng cao) Sweep tham số + walk-forward, báo cáo overfit | 02, 03 |
| 12 | [12-execution-realism.md](12-execution-realism.md) | (Nâng cao) Funding fee, margin guard, websocket, hiệu chỉnh slippage — 4 mục độc lập | 02/07/08 tuỳ mục |
| 13 | [13-alerts.md](13-alerts.md) | Alert center: Telegram + toast web UI + bảng alert DB, một event bus chung | 03 (Telegram dùng chung 07) |
| 14 | [14-chart-snapshot.md](14-chart-snapshot.md) | Ảnh chart ~100 nến + indicator + entry/SL/TP lúc mở/đóng lệnh để audit | 03; chụp tự động cần 07 |

Thứ tự đề xuất: **01 → 02 → 03 → 04 → 06 → 05 → 07 → 09 → (08 nếu muốn)**.
04 và 06 độc lập nhau, làm song song được. 09 chen vào bất cứ lúc nào sau 03.
Plan 10–12 là **nâng cao** — nằm ngoài định nghĩa "app hoàn chỉnh", user gọi khi cần
(10 mở thị trường forex; 11 là công cụ nghiên cứu; 12 xoá dần các deviation đã chấp nhận).
Plan 13–14 là **yêu cầu user 2026-07-18** (alert đa kênh + audit visual) — nên làm sau 03,
trước hoặc song song 07.

Tài nguyên user đã cung cấp: **DNSE Entrade API** (giao dịch phái sinh VN, có môi trường
papertrade, KHÔNG có dữ liệu nến) — <https://hdsd2.entrade.com.vn/entrade-api>; chi tiết
đã phân tích trong plan 08, tham chiếu ở plan 05 (lịch đáo hạn) và 07 (venue).

Quyết định user (2026-07-18): crypto chỉ làm **futures**, không spot; venue đầu tiên là
**Binance USDⓈ-M Futures** (klines công khai cho plan 07, testnet demo realtime + live
cùng API cho plan 08) — đã phản ánh trong plan 07 (§1) và 08 (BinanceFuturesAdapter).

Quyết định user (2026-07-18): **timeframe per-symbol** — phái sinh VN chạy **H4/D1**;
forex/crypto khung tự do (M15, H1, …). Phản ánh: plan 04 (`overrides.timeframe`),
05 (định nghĩa H4 phiên VN + warmup 1W), 02 (CSV native timeframe), 07 (LiveFeed interval
theo config). Ưu tiên user: **ít lỗ nhất, ít sự cố nhất, lời ít cũng được** — các đề xuất
an toàn tương ứng nằm ở plan 04 (❓ total risk cap), 07 (❓ weekend-flat), 08 (mục
"Chống sự cố khớp lệnh" + ❓2/❓4).

Quyết định user (2026-07-18, đợt 2): (a) risk/lệnh config qua UI — real bắt đầu **0.5%**,
user tự nâng dần (dự kiến tới 2%) — plan 08 §4 đã chốt; (b) **không bắt buộc** trần risk
tổng danh mục — `max_total_open_risk_pct` là field optional default tắt (plan 04);
(c) drawdown tổng từ đỉnh equity: WARN 5% / CRITICAL 10% — *quyết định "chỉ alert" đã bị
thay ở đợt 3 bên dưới* (plan 08 §2); (d) **quy tắc giữ lệnh theo khung**: TF ≤ H1 → không qua cuối tuần + không
giữ quá 8h kể cả sau TP1; TF > H1 (H4/D1…) → tự do, time-stop tắt (plan 07 §4, plan 05);
(e) thêm plan 13 (alert center: Telegram + toast web + log DB) và plan 14 (chụp ảnh chart
lúc mở/đóng lệnh).

Quyết định user (2026-07-18, đợt 3 — sau review toàn bộ plan theo tiêu chí ít-lỗ/ít-sự-cố):
(a) **drawdown CRITICAL 10% → TỰ CHUYỂN PAPER** (thay "chỉ alert" của đợt 2): chặn lệnh
real mới, vị thế mở vẫn quản tới SL/TP, arming lại thủ công — plan 08 §2, plan 13;
(b) **dialog xác nhận trên Config UI khi tắt cả hai filter adx + er** (fail-open →
breakout-mọi-lúc; chống click nhầm) — plan 09 §4, decisions.md mục Mapping;
(c) **12b (margin/liquidation guard) là prerequisite bắt buộc trước khi plan 08 arm real
cho crypto futures**; 12a (funding fee) là prerequisite để tin kết quả paper crypto
khung H4/D1 — đầu plan 08 + plan 12;
(d) **trần risk tổng `max_total_open_risk_pct` giữ là field config qua UI** — user tự đặt
giá trị (2%/4%/6% tuỳ giai đoạn), không ép default; risk/lệnh vốn đã config được (plan 08 §4);
plan 04 mở rộng overrides cho phép **`risk.max_risk_per_trade_pct` per-symbol**
(vd giảm nửa cho XAUUSD);
(e) **forex chống tương quan bằng WHITELIST cặp theo phiên** (thay correlation check §6.7):
EURUSD (London+NY), GBPUSD (London), USDJPY + USDCAD (NY), XAUUSD (chỉ overlap, risk nửa
mức) — bảng đầy đủ + quy tắc "tối đa 2 lệnh cùng hướng USD" ở plan 10 mục
"Cặp khuyến nghị theo phiên"; whitelist chính là mảng `symbols` của plan 04, không cần cơ chế mới.

## Bất biến (in vào đầu mọi plan — Sonnet, Opus phải giữ)

1. **Determinism** — `test_replay_golden` (seed 42) là chốt an toàn refactor. Plan nào đổi hành vi
   engine phải: chạy replay 2 lần xác nhận hash ổn định, re-pin hash mới, ghi 1 dòng vào
   `docs/decisions.md` giải thích vì sao hash đổi. Không bao giờ xoá test.
2. **`test_no_lookahead`** — bar chỉ thấy được khi `open_ts + tf_duration <= clock.now` (C11).
3. **`test_no_wallclock`** — cấm `datetime.now()`/`time.time()` trong engine; mọi thời gian qua `Clock`.
4. **Từ vựng reason §8 verbatim** — `wait|off|no_signal|no_confirm|mtf_conflict|dxy_conflict|daily_loss_limit_reached|max_concurrent_trades_reached|done`; ngữ cảnh thêm vào `stage`/`detail`, không thêm reason mới.
5. **Bộ đếm DERIVED** — `daily_loss_count`/streaks tính từ bảng `trade`; `account_state` chỉ là cache; `test_counters_consistent` phải giữ.
6. **Một chiều phụ thuộc** — `indicators → filters/strategies → engine → api`; 3 tầng đầu thuần pandas, không I/O (filter cần dữ liệu ngoài → nạp sẵn vào `Context`).
7. **Config versioned immutable** — mọi thay đổi config qua `PATCH /api/config` tạo version mới; decision row luôn trỏ về version sinh ra nó.
8. **mypy strict + ruff sạch**, frontend build không lỗi.
9. Frontend Config render từ `/api/config/schema` — thêm field config mới **không** cần sửa tay form.

## Định nghĩa "app hoàn chỉnh"

- Backtest được trên dữ liệu lịch sử thật, có phí, ra báo cáo metrics chuẩn (02+03).
- Chạy đa symbol để MAX_CONCURRENT_TRADES/daily-loss có nghĩa thật (04).
- Đủ 4 SYMBOL_TYPE gồm chứng khoán VN (05).
- Filter `news` có dữ liệu thật (06).
- Chạy live paper 24/7, sống sót restart, có cảnh báo (07).
- Đóng gói + vận hành được (09). Broker thật (08) là tuỳ chọn cuối, cần user chốt riêng.
