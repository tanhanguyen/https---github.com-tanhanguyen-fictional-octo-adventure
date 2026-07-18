# Plan 02 — Dữ liệu lịch sử thật (CSV) + chi phí giao dịch §10

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 01 đã xong.
> Mục tiêu: backtest chạy trên dữ liệu thị trường thật thay vì synthetic, có phí.

## Bối cảnh

- `data/csv_feed.py` đã có `load_csv_15m()` — đọc CSV 15m (index `open_ts`, cột
  open/high/low/close/volume), ép UTC, đi qua **cùng** pipeline `resample.build_all_timeframes`
  như synthetic → MTF consistency giữ nguyên về mặt cấu trúc.
- Bảng `dataset` trong SQLite hiện chỉ biết dataset synthetic (seed, bars).
- Filter `dxy` cần chuỗi DXY; hiện DXY cũng là synthetic.
- `instruments.yaml`: EURUSD `spread_pips: 0.0` — cố ý để test tính tay; §10 của spec yêu cầu
  backtest phải có chi phí.

## Quyết định cần USER chốt trước khi làm (hỏi nếu chưa có câu trả lời trong issue/chat)

1. **Nguồn dữ liệu**: user tự tải file (Dukascopy/HistData cho forex, Binance export cho crypto)
   và đặt vào `backend/data/csv/`. Plan này KHÔNG viết downloader gọi internet.
2. **Chuẩn cột CSV đầu vào** đề xuất: `open_ts,open,high,low,close,volume` UTC ISO-8601;
   viết sẵn script chuyển đổi `scripts/convert_csv.py` cho 2 format phổ biến
   (Dukascopy csv, Binance klines) → chuẩn trên.

## Việc cần làm

### 1. Dataset kind = `csv`

- Schema: thêm cột vào bảng `dataset`: `kind` (`synthetic|csv`), `source_path`, `file_sha256`,
  `symbol`, `start_ts`, `end_ts`, `bar_count`. Migration mới `002_dataset_csv.sql`
  (SQLite `ALTER TABLE ADD COLUMN`, giữ dữ liệu cũ với `kind='synthetic'`).
- `bot/data/dataset.py`: hàm đăng ký dataset từ CSV — validate khi import:
  - index tăng nghiêm ngặt, không trùng `open_ts`;
  - đúng lưới 15m (cho phép **thiếu** bar — cuối tuần forex — nhưng không lệch lưới);
  - `high >= max(open,close)`, `low <= min(open,close)`, không NaN;
  - báo lỗi rõ ràng (FeedError) kèm dòng đầu tiên vi phạm.
  - Chính sách gap: KHÔNG fill — engine vốn xử lý chuỗi bar đóng tuần tự; ghi số gap vào
    metadata dataset để hiển thị.
- **Native timeframe** (phục vụ quyết định 2026-07-18: VN chạy H4/D1, dữ liệu VN thường
  không có 15m): bảng `dataset` thêm cột `native_tf` (`15m|1H|4H|1D`); `load_csv_15m`
  tổng quát hoá thành `load_csv(path, tf)` — validate lưới theo đúng tf khai báo;
  `build_all_timeframes` nhận base tf và **chỉ resample lên** (base 1D thì không có 15m/1H —
  hợp lệ). Ràng buộc khi tạo run: `dataset.native_tf` phải ≤ `config.timeframe`
  (mịn hơn hoặc bằng), sai → lỗi rõ ràng lúc tạo run chứ không chạy ra kết quả rác.
  Intrabar path-priority (plan 01) chỉ tồn tại với synthetic 15m — CSV native thô hơn
  fallback `sl_first` như đã ghi.
- API: `POST /api/datasets/import {path, symbol}` (đường dẫn server-side dưới `backend/data/csv/`
  — không upload multipart để giữ đơn giản), `GET /api/datasets` trả thêm metadata mới.
- CLI: `python -m bot.cli import-csv --path … --symbol EURUSD`, và
  `replay --dataset <id>` chạy trên dataset đã import (bên cạnh `--seed/--bars` cũ).

### 2. DXY thật

- Chuỗi DXY import y như giá (CSV 15m hoặc 1H — nếu 1H thì chuẩn hoá: filter `dxy`
  chỉ dùng khung 1H nên nhận trực tiếp), đăng ký như dataset `symbol='DXY'`, liên kết
  với run qua config (`filters.dxy.dataset_id` hoặc quy ước tên).
- **Căn chỉnh thời gian**: giá trị DXY nhìn thấy tại clock t = bar DXY đã đóng gần nhất
  (cùng quy tắc C11, forward-nhìn-lùi, không ffill tương lai). Nếu DXY thiếu bar tại thời điểm
  đánh giá → filter trả `passed=None, stage="no_data"` (không chặn), ghi detail.
- Nếu user chưa có dữ liệu DXY: filter `dxy` off là hợp lệ, không block plan.

### 3. Chi phí giao dịch (§10)

- Config mới dưới `execution.costs`: `spread_pips` (đã có trong instrument — chuyển thành
  giá trị active per-run qua config để version hoá), `commission_per_lot` (USD, tính lúc đóng),
  `slippage_pips` (cộng bất lợi vào giá fill entry VÀ giá fill SL; TP giữ nguyên — mô hình bảo thủ).
- Áp trong `order_engine` tại điểm fill/close — KHÔNG rải ra nơi khác. Buy fill =
  `open + (spread+slippage)×pip`; Sell fill = `open − …`; SL exit xấu đi slippage.
- Default tất cả = 0 → golden hash cũ không đổi vì chi phí; thêm golden thứ hai
  `test_replay_golden_with_costs` (seed 42, costs bật) pin hash riêng.
- README mục §5: thêm bước so equity có phí vs không phí (phí > 0 ⇒ equity cuối phải thấp hơn
  hoặc bằng — assert trong test integration).

### 4. Volume filter cho crypto

- Với dataset crypto (volume thật có nghĩa): kiểm filter `volume` hoạt động đúng
  (default off cho FOREX theo decisions.md — giữ nguyên; bật qua config khi symbol_type=CRYPTO).
  Chỉ cần test + ghi chú, không đổi code filter trừ khi phát hiện sai.

### 5. Frontend

- Trang/section Datasets: bảng dataset (kind, symbol, khoảng thời gian, bar count, gaps, hash),
  nút tạo synthetic (đã có) + form import CSV (nhập path). Chọn dataset khi tạo run.

## Determinism với dữ liệu thật

Cùng `dataset_id` + cùng config version ⇒ cùng `decision_stream_hash`. `file_sha256` bảo đảm
dataset bất biến; import lại file khác nội dung → dataset id mới. Thêm test: import cùng file
2 lần → trả về cùng dataset (idempotent theo sha256).

## Definition of done

- Import một CSV EURUSD 15m thật (hoặc fixture ~2000 bar cắt từ dữ liệu thật đặt trong
  `tests/fixtures/csv/`), `replay --dataset` chạy hết, sinh lệnh, hash ổn định qua 2 lần chạy.
- Costs bật làm equity giảm tương ứng, golden-with-costs pin xong.
- Toàn bộ test/mypy/ruff xanh; `docs/decisions.md` bổ sung mục "Dữ liệu thật & chi phí"
  (chính sách gap, căn DXY, mô hình slippage bảo thủ).
