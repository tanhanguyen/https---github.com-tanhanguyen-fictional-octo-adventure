# Plan 13 — Alert center: Telegram + toast web UI + log DB

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: 03 (nề nếp DB/API/UI);
> phần Telegram dùng chung `bot/notify.py` của plan 07 — nếu plan 07 chưa làm,
> phần Telegram ở đây thay thế luôn mục đó (07 chỉ cần gọi `alerts.emit`).
> Yêu cầu user (2026-07-18): mọi sự kiện quan trọng vừa alert qua **Telegram**,
> vừa **toast trên web UI**, vừa **log lại ở backend**.

## Danh mục sự kiện (đề xuất của Fable — user cắt/thêm khi review)

| Code | Level | Khi nào |
|---|---|---|
| `trade_opened` | INFO | lệnh fill (symbol, side, lot, entry/SL/TP, risk %) |
| `trade_pending` | INFO | signal đặt lệnh chờ retest — **default tắt** (nhiều, ồn) |
| `trade_cancelled` | INFO | huỷ pending (D7 guard, hết hạn retest) |
| `tp1_hit` | INFO | chốt 50% + dời SL về BE |
| `trade_closed` | INFO | đóng lệnh (SL/TP/BE/time_stop/weekend_close/expiry — kèm R, PnL, equity mới) |
| `daily_loss_limit` | WARN | chạm 3 lệnh thua/ngày → nghỉ hết ngày |
| `equity_multiplier` | WARN | equity-curve filter kích hoạt giảm size (0.3×/0.5×) |
| `drawdown_warn` | WARN | drawdown tổng từ đỉnh equity chạm **5%** (plan 08 §2) |
| `drawdown_critical` | CRITICAL | drawdown tổng chạm **10%** — kèm hành động **tự chuyển paper** (plan 08 §2, user chốt 2026-07-18 đợt 3; chỉ chặn lệnh real mới, vị thế mở vẫn quản tới SL/TP) |
| `feed_degraded` / `feed_recovered` | WARN / INFO | mất/khôi phục dữ liệu live (plan 07) |
| `order_error` | ERROR | lỗi đặt/sửa lệnh broker (plan 08) |
| `naked_position_closed` | CRITICAL | đặt SL thất bại → đóng vị thế khẩn cấp (plan 08, quy tắc 2) |
| `circuit_breaker` | CRITICAL | ~3 lỗi API liên tiếp → tự về paper (plan 08, quy tắc 5) |
| `desynced` | CRITICAL | reconciliation lệch lúc boot (plan 08, quy tắc 4) |
| `runner_stopped` / `runner_started` | WARN / INFO | process live dừng/chạy lại |
| `snapshot_error` | WARN | render ảnh chart lỗi (plan 14) — không được crash runner |
| `daily_summary` | INFO | 1 tin/ngày: số lệnh, PnL, equity, drawdown |

## Kiến trúc

- **Engine KHÔNG phát alert** (bất biến #6 — 3 tầng đầu thuần pandas, không I/O).
  Tầng runner/live_runner quan sát `trade_event` + decision + trạng thái hệ thống
  rồi gọi `alerts.emit(...)`. Test import: `bot/engine/*`, `bot/filters/*`,
  `bot/strategies/*` không import `bot/alerts`.
- `bot/alerts/bus.py`: `emit(code, level, title, body: dict, run_id)` → fan-out:
  1. **DB luôn ghi** (nguồn chân lý / log backend): bảng
     `alert(id, run_id, ts, level, code, title, body_json, sent_telegram, read)`.
  2. **Telegram** nếu có token (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` qua env):
     lỗi gửi KHÔNG được lan ra ngoài `emit` (runner không bao giờ crash vì alert) —
     ghi `sent_telegram=false`, thử lại ở lần emit sau.
  3. Web UI không cần push — frontend poll (bên dưới).
- **Chống spam**: cùng `code` (+ key symbol nếu có) trong cửa sổ cooldown (mặc định
  10 phút, config được) → gộp lại, không bắn Telegram lặp. **CRITICAL không bao giờ
  bị gộp/nuốt.**
- Ngưỡng gửi Telegram config được (mặc định: INFO trở lên; riêng `trade_pending` tắt).

## API + frontend

- `GET /api/alerts?since_id=&level=&limit=` (mới nhất trước);
  `POST /api/alerts/read` đánh dấu đã đọc (danh sách id).
- Frontend: hook poll ~10s với `since_id` → **toast** cho alert mới (INFO tự tắt sau
  vài giây; WARN nổi bật; CRITICAL đỏ, không tự tắt, phải bấm đóng); icon chuông
  trên header với badge số chưa đọc + dropdown lịch sử. Thư viện toast nhẹ
  (sonner / react-hot-toast) hoặc tự viết — chọn một, ghi lý do vào decisions.md.

## Kiểm thử

- Bus test với channel giả: fan-out đúng, DB luôn có row, cooldown gộp đúng,
  CRITICAL không bị gộp, exception từ Telegram không thoát ra khỏi `emit`.
- Test import một chiều phụ thuộc (như trên).
- API test: danh sách, `since_id`, đánh dấu đọc.
- Không test nào gọi Telegram thật (HTTP mock).

## Definition of done

- Chạy replay + live paper: mở/đóng lệnh sinh alert trong DB, toast hiện trên web,
  Telegram nhận tin (hoặc log-only khi không có token); mypy strict/ruff/test xanh;
  decisions.md ghi danh mục event đã chốt với user.
