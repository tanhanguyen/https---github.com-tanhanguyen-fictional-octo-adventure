# Roadmap: từ mock end-to-end → app hoàn chỉnh

Trạng thái hiện tại (đã xong, commit `1825b99`): Phases 1–5 của plan gốc — core thuần pandas
(indicators/filters/strategies), engine (main_loop evaluate-all-decide-after, order_engine
fill-at-next-open, runner), mock synthetic feed, SQLite (counters DERIVED, config versioned),
FastAPI REST, React dashboard 4 trang. Toàn bộ chạy trên **dữ liệu mock, 1 symbol (EURUSD), paper**.

Nguồn chân lý: `docs/spec_v1_2.md` **cho mọi thứ trừ chiến lược breakout**; từ 2026-07-26
chiến lược breakout theo `docs/spec_v2.md` (BRB — Breakout → Retest → Breakout + ma trận
điểm số), xem hàng 15 bảng dưới. Mọi quyết định & sai lệch: `docs/decisions.md` (D1–D11,
C1–C12, 21 deviations). **Ràng buộc xuyên suốt: không tự thêm chiến lược/bộ lọc ngoài spec.**

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
| 12 | [12-execution-realism.md](12-execution-realism.md) | (Nâng cao) Funding fee, margin guard, websocket, hiệu chỉnh slippage, **12e: độ thật chứng khoán VN** — 5 mục độc lập | 02/07/08 tuỳ mục (12e sau 05) |
| 13 | [13-alerts.md](13-alerts.md) | Alert center: Telegram + toast web UI + bảng alert DB, một event bus chung | 03 (Telegram dùng chung 07) |
| 14 | [14-chart-snapshot.md](14-chart-snapshot.md) | Ảnh chart ~100 nến + indicator + entry/SL/TP lúc mở/đóng lệnh để audit | 03; chụp tự động cần 07 |
| 15 | [docs/spec_v2.md](../docs/spec_v2.md) | **BRB**: breakout→retest→breakout (vào lệnh sau khi phá Peak1), ma trận điểm số 12 tiêu chí, guard khoảng cách SL. Không có file plan riêng — spec là plan; ghi chép triển khai ở `docs/decisions.md` mục "BRB v2" | 03 (đo được), 05 (profile VN) |

Thứ tự đề xuất: **01 → 02 → 03 → 04 → 06 → 05 → 07 → 09 → (08 nếu muốn)**.
04 và 06 độc lập nhau, làm song song được. 09 chen vào bất cứ lúc nào sau 03.
Plan 10–12 là **nâng cao** — nằm ngoài định nghĩa "app hoàn chỉnh", user gọi khi cần
(10 mở thị trường forex; 11 là công cụ nghiên cứu; 12 xoá dần các deviation đã chấp nhận).
Plan 13–14 là **yêu cầu user 2026-07-18** (alert đa kênh + audit visual) — nên làm sau 03,
trước hoặc song song 07.

Tài nguyên user đã cung cấp — **hai hệ thống DNSE khác nhau, đừng lẫn**:

- **DNSE Entrade API** (<https://hdsd2.entrade.com.vn/entrade-api>) — *giao dịch* phái sinh
  VN, có môi trường papertrade, **KHÔNG có dữ liệu nến**. Dùng cho plan 08 (đặt lệnh) và
  plan 05 (lịch đáo hạn).
- **DNSE OpenAPI / LightSpeed** (<https://developers.dnse.com.vn>) — *dữ liệu thị trường*,
  **CÓ đầy đủ OHLC** cho cổ phiếu, phái sinh và chỉ số: REST `GET /price/ohlc` (lịch sử) +
  WebSocket `ohlc_closed` (realtime). Đã triển khai (2026-07-23) làm feed live cho cả
  `STOCK_VN_CASH` và `STOCK_VN_DERIV` — xem `docs/decisions.md` mục "Plan 07b".

Quyết định user (2026-07-18): crypto chỉ làm **futures**, không spot; venue đầu tiên là
**Binance USDⓈ-M Futures** (klines công khai cho plan 07, testnet demo realtime + live
cùng API cho plan 08) — đã phản ánh trong plan 07 (§1) và 08 (BinanceFuturesAdapter).

Quyết định user (2026-07-18): **timeframe per-symbol** — phái sinh VN chạy **H4/D1**;
forex/crypto khung tự do (M15, H1, …). Phản ánh: plan 04 (`overrides.timeframe`),
05 (định nghĩa H4 phiên VN + warmup 1W), 02 (CSV native timeframe), 07 (LiveFeed interval
theo config). Ưu tiên user: **ít lỗ nhất, ít sự cố nhất, lời ít cũng được** — các đề xuất
an toàn tương ứng nằm ở plan 04 (❓ total risk cap), 07 (❓ weekend-flat), 08 (mục
"Chống sự cố khớp lệnh" + ❓2/❓4) — *các ❓ này đã được chốt ở đợt 2–3 bên dưới,
chỉ còn ❓ max-lot/max-lệnh-ngày (08 ❓2) và các ❓ gắn mốc thời gian demo là mở.*

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

Quyết định user (2026-07-22, plan 05 — chứng khoán VN): (a) **T+2.5 chặn thoát lệnh**
(SL/TP không kích trước khi hàng về, chỉ ghi `exit_suppressed_settlement`); (b) VN30F
**chỉ D1**, không định nghĩa bar H4 trên phiên VN; (c) **tài khoản VND riêng**, cấm trộn
symbol VN với FOREX/CRYPTO trong một run; (d) không đủ 1 lô nguyên → `wait`/`lot_below_min`;
(e) chuỗi VN30F liên tục bằng **script `stitch_vn30f.py`** ngoài engine; (f) chấp nhận cả 4
đơn giản hoá (tick HOSE, trần/sàn ±7%, đáo hạn thuần lịch, không margin) — **gom thành plan
nâng cao 12e**. Chi tiết + lý do: `docs/decisions.md` mục "Plan 05".

Quyết định user (2026-07-26, BRB v2 — plan 15): chiến lược breakout chuyển sang
**Breakout → Retest → Breakout**: vào lệnh sau khi phá `Peak1` (đỉnh xung lực ≥1×ATR trên
range) thay vì ngay tại nến retest — sửa gốc lỗi "SL bị quét trong 1 nến" (entry cũ ≈
`range_high` ⇒ 1R ≈ 0.5×ATR). User chốt làm **cả hai**: BRB đầy đủ **và** guard khoảng cách SL
trực tiếp (`min_stop_atr_mult`/`max_sl_atr_mult`). `require_second_breakout=false` giữ nguyên
máy trạng thái v1.2 để A/B. Chi tiết + 5 điểm giải mâu thuẫn spec_v2 vs bất biến engine (D6
khớp-ở-open, deviation #7 TP-chốt-lúc-fill, D5 retest-theo-ATR, TP2 = R cố định thay vì
trailing fractal): `docs/decisions.md` mục "BRB v2".

Quyết định user (2026-07-30, plan 11 — sweep + walk-forward): (a) ❓2 metric chọn tham số
trên IS = **profit factor**, ràng buộc **max_drawdown ≤ 20%** và **số lệnh ≥ 30**;
(b) ❓3 cửa sổ walk-forward = **IS 12 tháng / OOS 3 tháng / trượt 3 tháng**; (c) dataset thật
= **EURUSD 1H** (`data/csv/EURUSD_real_1h.csv`, 2010-07 → 2026-07). Kết quả sweep thật đầu
tiên + mọi quyết định triển khai: `docs/decisions.md` mục "Plan 11".

**Cảnh báo cho mọi plan sau**: BRB đổi ý nghĩa của "nến quyết định". Ở v1.2 nến quyết định
*là* nến retest; ở BRB nó là nến **breakout-2**, còn nến retest nằm `signal.retest_bars_ago`
bar trước đó. Bất kỳ filter/report/snapshot nào cần soi "nến retest" **phải** dùng offset đó,
không dùng `iloc[-1]` — đây chính là lỗi đã làm filter `wick` chặn sạch tín hiệu BRB
(`docs/decisions.md` mục "Sửa 4 lỗi ghép nối của BRB").

**Calibration là việc còn mở, không thuộc plan 15.** BRB + scoring siết phễu rất mạnh; trên
dữ liệu synthetic (random-walk) tần suất lệnh gần 0 vì hai tiêu chí A1 (thân nến > 2×SMA10)
và B2 (engulfing) hầu như không xảy ra. Hiệu chỉnh ngưỡng cần **dữ liệu thật** — đã đưa vào
plan 11 (❓1) làm trục sweep, không phải sửa code.

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
