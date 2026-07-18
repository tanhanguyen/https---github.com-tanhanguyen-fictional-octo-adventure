# Plan 14 — Chart snapshot: ảnh ~100 nến lúc mở/đóng lệnh để audit

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: 03 (trang Trades, bar trong
> DB); phần chụp tự động lúc live cần 07; alert lỗi render dùng plan 13.
> Yêu cầu user (2026-07-18): khi xem lại lệnh có hình chart để đối chiếu công thức
> indicator + lý do vào lệnh. User chọn phương án **chụp ảnh** (chất lượng vừa đủ
> thấy rõ indicator và giá) thay vì chỉ lưu dữ liệu nến.

## Thiết kế

- `bot/report/snapshot.py`: render PNG bằng **mplfinance** (matplotlib, backend Agg
  headless). KHÔNG nằm trong engine (bất biến #6) — tầng runner gọi sau sự kiện
  fill/close; engine không import matplotlib (test import).
- **Nội dung ảnh**: ~100 bar cuối của đúng `trade.timeframe`; overlay EMA34/EMA89;
  range high/low của breakout (nếu strategy breakout) / EMA34 high-low band (nếu MR);
  đường ngang entry/SL/TP (và TP1 + BE nếu đã partial); marker tại bar signal và bar
  fill/close; tiêu đề: symbol, TF, strategy, thời điểm, reason/stage từ decision row.
  Kích thước đề xuất **1200×700, dpi 100** (~60–120KB/ảnh) — ❓ user chỉnh nếu muốn.
- **Nguồn dữ liệu vẽ**: đúng frame engine đã thấy tại bar đó (cùng pipeline resample,
  cùng cách tính indicator) — ảnh phải tái hiện cái bot nhìn thấy lúc quyết định,
  không phải dữ liệu tải lại sau này.
- **Lưu trữ**: `backend/data/snapshots/{run_id}/{trade_id}_open.png` và
  `{trade_id}_close.png` — đường dẫn theo quy ước, không cần cột DB mới;
  API mount static `GET /api/snapshots/{run_id}/{filename}`.
- **Khi nào chụp**:
  - Run **live/paper** (plan 07): mặc định **bật** — chụp lúc fill và lúc đóng
    (mỗi lệnh 2 ảnh; ~100ms/ảnh, chấp nhận được ở tần suất lệnh thực tế).
  - **Backtest/replay**: mặc định **tắt** (ngàn lệnh = ngàn ảnh + chậm + phá golden
    về thời gian chạy) — thay bằng render **on-demand**:
    `GET /api/trades/{id}/snapshot?at=open|close` dựng ảnh từ dữ liệu DB ngay lúc gọi;
    vì dữ liệu + config version còn nguyên và deterministic, kết quả y hệt chụp lúc
    chạy. ❓ flag config bật eager cho backtest nếu user muốn.
- **Retention**: ❓ đề xuất gắn theo run — xoá run thì xoá thư mục ảnh; không tự xoá
  theo ngày.
- **Trang Trades**: thêm thumbnail (lazy-load) mỗi lệnh + click mở modal ảnh to
  (open/close cạnh nhau); trade backtest chưa có ảnh → nút "Render" gọi endpoint
  on-demand.
- Lỗi render KHÔNG được crash runner live: try/except quanh lời gọi, phát alert
  `snapshot_error` (WARN, plan 13), lệnh vẫn xử lý bình thường.

## Kiểm thử

- Từ frame cố định (seed): render ra file PNG tồn tại, size > 0; kiểm bằng dữ liệu
  (không so pixel): các đường entry/SL/TP nằm trong khoảng trục y, số bar vẽ ≤ 100,
  đúng timeframe.
- Render on-demand cho một trade backtest bất kỳ trả ảnh hợp lệ; trade không tồn tại → 404.
- Exception giả trong renderer → runner tiếp tục, có alert `snapshot_error`.
- Engine/filters/strategies không import matplotlib/mplfinance.

## Definition of done

- Live paper: mở/đóng lệnh sinh ảnh, xem được thumbnail + modal trên trang Trades;
  trade backtest render on-demand hoạt động; mypy strict/ruff/test xanh;
  decisions.md ghi kích thước ảnh + retention đã chốt.
