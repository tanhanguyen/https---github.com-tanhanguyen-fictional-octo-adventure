# Plan 04 — Đa symbol: portfolio thật cho MAX_CONCURRENT_TRADES

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 01 (nên làm sau 03 để report
> per-symbol có chỗ hiển thị). Đây là plan đổi engine sâu nhất — hash golden chắc chắn re-pin.

## Bối cảnh

- Hiện engine chạy **1 symbol**: `OrderEngine`/`Runner` nhận `OpenTrade | None`
  (ghi chú sẵn trong `order_engine.py`); `account_state.open_trades` chỉ 0/1.
- Deviation #13: vì 1 symbol, khối `ONE_TRADE_PER_SYMBOL` emit
  `reason="max_concurrent_trades_reached", stage="one_trade_per_symbol"` để giữ từ vựng §8.
- §6.7: `MAX_CONCURRENT_TRADES` Forex/Crypto = 3, Stock VN = 2 (D10); daily loss count
  là **toàn tài khoản**, không per-symbol.
- D2 đã bỏ bảng tham số per-symbol §7 — plan này đưa lại một lớp profile **mỏng**
  (không phải nguyên bảng §7).

## Thiết kế

### Config

- `symbols`: danh sách entries `{symbol, symbol_type, dataset/seed, enabled, overrides}` —
  `overrides` là deep-merge lên config gốc **giới hạn trong** `filters.*`, `strategy.*`,
  **`timeframe`**, **`risk.allow_short`** và **`risk.max_risk_per_trade_pct`**
  (không override account/execution — các thứ đó
  là toàn tài khoản; `allow_short` là per-symbol theo D11, `timeframe` per-symbol theo
  quyết định user 2026-07-18: VN30F chạy **H4/D1**, forex/crypto khung tự do **M15/H1/…**;
  `max_risk_per_trade_pct` per-symbol theo user 2026-07-18 đợt 3 — để đặt risk thấp hơn
  cho symbol biến động cao như XAUUSD, xem plan 10 mục "Cặp khuyến nghị theo phiên").
  Mảng `symbols` đồng thời đóng vai trò **whitelist chống tương quan** của user
  (chỉ trade cặp có trong danh sách — không cần cơ chế mới).
- **Instrument spec phải per-symbol** (phát hiện khi rà lần cuối 2026-07-18): các tham số
  `pip`, `pip_value_per_lot`, `contract_size`, `min_lot`, `spread_pips` hiện là config
  toàn cục chuẩn EURUSD (decisions.md mục Gap). USDJPY có `pip = 0.01` (khác 100 lần),
  XAUUSD khác hẳn — dùng chung spec EURUSD sẽ **sizing sai lot** → chuyển instrument spec
  vào entry của từng symbol (hoặc bảng instrument tra theo symbol). Migrate: config cũ
  1 symbol lấy spec toàn cục hiện có. Có test sizing cho ít nhất một symbol pip=0.01.
- Mỗi symbol một timeframe ⇒ mốc bar-close mỗi symbol khác nhau — cơ chế "hợp nhất mốc
  clock" bên dưới phải có test với TF hỗn hợp (ví dụ 15m + 1D chạy chung), không chỉ
  cùng-TF-lệch-lịch. Schema-driven UI
  tự render nhờ `/api/config/schema` (kiểm rằng metadata sinh đủ cho nested list; nếu form
  list phức tạp quá thì UI cho phép sửa JSON của mảng `symbols` + validate server-side, chấp nhận được).
- Giữ tương thích: config cũ 1 symbol tự migrate thành `symbols: [«symbol cũ»]` khi load.

### Engine

- `OpenTrade | None` → `list[OpenTrade]` xuyên suốt `main_loop`/`OrderEngine`/`Runner`.
- Mỗi symbol có state chiến lược riêng (máy trạng thái retest, confirmation lag…) —
  đóng gói `SymbolContext` (frames, indicators, strategy state) trong `engine/context.py`.
- **Thứ tự bar xử lý phải deterministic**: tại mỗi mốc clock, xử lý các symbol có bar đóng
  tại mốc đó theo thứ tự **alphabet của symbol**. Runner advance clock theo hợp nhất các mốc
  bar-close của mọi symbol (các symbol có thể lệch lịch — forex nghỉ cuối tuần, crypto không).
- Kiểm tra tài khoản (§8 bước 0) trước từng quyết định, dùng trạng thái portfolio hiện hành:
  - `ONE_TRADE_PER_SYMBOL`: đã có lệnh mở/pending trên symbol đó →
    reason `max_concurrent_trades_reached`, stage `one_trade_per_symbol` (giữ deviation #13);
  - tổng lệnh mở ≥ `MAX_CONCURRENT_TRADES` → cùng reason, stage `max_concurrent_trades`.
  - `daily_loss_count` toàn tài khoản (theo trading day C3) — đã derived từ bảng `trade`,
    tự đúng khi nhiều symbol, chỉ cần test.
- Risk: `MAX_RISK_PER_TRADE` per lệnh giữ nguyên — config được qua UI như mọi tham số
  (user chốt 2026-07-18: real bắt đầu 0.5%/lệnh, tự nâng dần qua Config UI, xem plan 08 §4).
  **Trần risk tổng danh mục — ĐÃ CHỐT (user 2026-07-18): KHÔNG bắt buộc.** User chọn
  quản lý bằng risk/lệnh + daily-loss-limit (3 thua/ngày). Vẫn thêm field
  `risk.max_total_open_risk_pct: float | None`, **default None = tắt** (không đổi hành vi,
  không đổi golden hash); ai muốn thì bật qua Config UI — khi bật, tổng risk các lệnh
  mở/pending vượt ngưỡng → chặn lệnh mới, reason `max_concurrent_trades_reached`,
  stage `total_risk_cap`. Ghi chú toán (đã trình user): tắt trần → worst-case một ngày
  = MAX_CONCURRENT × risk/lệnh (3 × 2% = 6%; 3 × 0.5% = 1.5%), vì daily-loss-limit chỉ
  chặn SAU KHI đã đủ 3 lệnh thua.
- Synthetic đa symbol: mỗi symbol một child RNG stream đặt tên (`child(symbol)`) từ seed gốc —
  thêm symbol mới không đổi stream của symbol cũ (giữ triết lý named child streams hiện có).

### DB / API / UI

- Kiểm cột `symbol` đã có trên `trade`/`decision` chưa; thiếu đâu migration bổ sung đó.
- API list trades/decisions thêm query `symbol=`; account snapshot trả breakdown
  `open_trades_by_symbol`.
- UI: cột symbol + bộ lọc symbol ở Decisions/Trades; Dashboard hiện bảng vị thế đủ symbol.

## Kiểm thử

- Unit: dựng 2–3 symbol synthetic, ép tình huống: (a) 3 lệnh mở → symbol thứ 4 có signal bị chặn
  đúng reason/stage; (b) 2 signal cùng mốc clock → thứ tự alphabet quyết định lệnh nào ăn slot
  cuối; (c) một symbol thua 3 lệnh trong ngày → symbol khác cũng bị `daily_loss_limit_reached`.
- `test_no_lookahead`/`test_no_wallclock` giữ nguyên hiệu lực trên đường code mới.
- Golden: chạy config 1-symbol cũ qua đường code mới — **hành vi phải giống hệt** bản trước
  (hash chỉ đổi nếu có lý do ghi được thành lời; lý tưởng là không đổi với 1 symbol).
  Thêm golden thứ hai cho 3 symbol.

## Definition of done

- Replay 3 symbol chạy hết, `max_concurrent_trades_reached` xuất hiện với **cả hai** stage
  trong histogram; counters portfolio đúng; test/mypy/ruff xanh; decisions.md cập nhật
  (mục list[OpenTrade] và thứ tự symbol deterministic; xoá ghi chú "0/1" cũ).
