# Plan 03 — Backtest analytics: metrics, run registry, trang Report

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 02.
> Mục tiêu: một lần backtest trả lời được "chiến lược này có ăn không, rủi ro thế nào,
> filter nào đáng tiền" — bằng số, không phải cảm giác.

## Bối cảnh

- DB đã có bảng `run`, `trade`, `trade_event`, `decision`, `decision_filter`, `equity_point`;
  API hiện chỉ thao tác trên **run đang active** của `RunnerService`.
- Equity chart + decision histogram đã có ở frontend nhưng chưa có metrics tổng hợp.

## Việc cần làm

### 1. Module metrics (thuần, không I/O) — `bot/analytics/metrics.py`

Input: danh sách trade đã đóng + chuỗi equity point (lấy từ repositories, nhưng hàm tính nhận
list/DataFrame thuần để test tay được). Output dataclass `RunReport`:

- Tổng quan: số lệnh (tổng / BREAKOUT / MEAN_REVERSION / BUY / SELL), win rate
  (WIN vs LOSS+BREAKEVEN — nhất quán D8, ghi rõ trong report), profit factor
  (gross win / gross loss), expectancy theo R (mean R-multiple; R = pnl / risk_tại_lệnh),
  avg/max win, avg/max loss, avg thời gian giữ lệnh (giờ), phân bố R-multiple (histogram bins).
- Chuỗi: max drawdown tuyệt đối + %, thời gian drawdown dài nhất (bar), equity cuối,
  return tổng %, Sharpe đơn giản trên per-bar returns (ghi chú: chỉ để so sánh tương đối
  giữa các run, không annualize màu mè — annualization factor theo timeframe, ghi công thức
  vào docstring).
- Decision-side: histogram reason (đã có ở decision_stats — tái dùng), tỷ lệ
  signal-bị-chặn theo từng filter (đếm decision_filter rows có `blocking=true` group by filter id)
  → trả lời "filter nào chặn nhiều nhất".
- Từng số phải có unit test tính tay (fixture 5–10 trade dựng tay, đúng phong cách
  `tests/fixtures/indicators/` với trường `derivation`).

### 2. Run registry — nhiều run, so sánh được

- `RunnerService` hiện gắn 1 run active. Giữ nguyên model đó cho play/step, nhưng:
  - `GET /api/runs` — list mọi run trong DB (id, created, dataset, config version, trạng thái,
    bar đã chạy, equity cuối);
  - `GET /api/runs/{id}/report` — chạy metrics trên run bất kỳ (kể cả run cũ);
  - `GET /api/runs/{id}/trades|decisions|equity` — read-only cho run cũ (tái dùng query hiện có,
    thêm tham số run_id thay vì mặc định run active);
  - `DELETE /api/runs/{id}` — dọn run cũ (cấm xoá run đang active).
- CLI: `python -m bot.cli replay …` in thêm bảng `RunReport` tóm tắt cuối phiên.

### 3. So sánh A/B hai run

- `GET /api/runs/compare?a={id}&b={id}`: cùng dataset? cùng config? diff các metrics chính
  + diff histogram reason. Đây là bản API-hoá của harness `bot.cli ab` (plan 01) —
  harness đó có thể refactor để dùng chung phần diff.

### 4. Frontend

- **Trang Report** (route mới `/runs/:id/report`): cards metrics, bảng per-strategy,
  histogram R-multiple (bar chart), drawdown chart (dưới equity), bảng "filter nào chặn
  bao nhiêu signal". Link từ trang Runs.
- **Trang Runs**: bảng run + nút xem report / so sánh 2 run (chọn 2 checkbox → bảng diff).
- **Chart nến + trade markers** trên Dashboard: dùng thư viện `lightweight-charts`
  (TradingView, MIT, nhẹ, không cần backend đổi gì ngoài endpoint bars:
  `GET /api/runs/{id}/bars?tf=1H&from=&to=` trả OHLC đã đóng tới bar hiện tại của run).
  Markers: entry (mũi tên theo direction), SL/TP lines của trade đang mở, exit markers.
  Đây là phần việc frontend lớn nhất — làm sau cùng, các phần trên không phụ thuộc nó.
  - **Overlay EMA34 + EMA89** (bổ sung 2026-07-24): endpoint `bars` trả thêm 2 cột
    `ema34`, `ema89` mỗi nến; frontend vẽ 2 `LineSeries` (EMA34 xanh, EMA89 cam — cùng
    bảng màu với ảnh snapshot plan 14 để nhìn 2 nơi thấy như nhau). Ràng buộc quan trọng:
    EMA là chỉ báo đệ quy → phải tính trên **toàn bộ lịch sử đã đóng** của run (seed bằng
    SMA `period` nến đầu), KHÔNG tính lại trên cửa sổ `from/to/limit` (sẽ sai ở mép trái).
    EMA phải **causal / no-lookahead**: giá trị tại nến t chỉ phụ thuộc nến ≤ t, nên khi
    step thêm 1 nến các giá trị cũ không đổi (đã kiểm trong
    `test_bars_no_lookahead_grows_one_candle_per_step`). Những nến còn trong giai đoạn
    warmup (chưa đủ `period` nến để seed SMA) trả `null` — frontend bỏ qua khi vẽ.

## Ràng buộc

- Metrics là **read-only** trên dữ liệu đã ghi — không đụng engine, hash golden không đổi.
- Không thêm tối ưu tham số / grid search trong plan này (spec không yêu cầu; nếu user muốn
  thì đó là plan riêng, cần chốt phạm vi chống overfitting).

## Definition of done

- `pytest` xanh (metrics tính tay khớp fixture), mypy/ruff sạch.
- Chạy replay seed 42 → mở trang Report thấy đủ metrics; so sánh 2 run khác config version
  ra bảng diff đúng.
- Chart nến hiển thị đúng bar đã đóng (không lộ bar tương lai — kiểm bằng cách step từng bar
  và xem chart chỉ dài thêm 1 nến mỗi step).
