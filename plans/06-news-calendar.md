# Plan 06 — Dữ liệu cho filter `news` (blackout windows)

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 02 (hạ tầng import).
> Plan nhỏ. Hiện `NEWS_BLACKLIST=[]`, filter off — mục tiêu: cấp dữ liệu thật cho nó.

## Bối cảnh

- Filter `news` (GATE) đã tồn tại, nhận "list khoảng UTC nhập tay" (decisions.md, mục Gap).
- Bất biến #6: filter thuần, không I/O — dữ liệu sự kiện phải được nạp sẵn vào `Context`.
- Determinism: sự kiện tin tức là **input của run** — phải bất biến sau khi run tạo.

## Thiết kế

### 1. Nguồn & format

- User tự export lịch kinh tế (ví dụ ForexFactory calendar CSV — tải tay, KHÔNG scrape/gọi API).
- Chuẩn nội bộ: bảng `news_event` — `id, ts_utc, currency (USD/EUR/…), impact (high|medium|low),
  title, source_file_sha256`. Script `scripts/convert_news.py` đổi format ForexFactory → chuẩn.
- Import: CLI `python -m bot.cli import-news --path …` + `POST /api/news/import {path}`;
  validate ts hợp lệ, dedupe theo (ts, currency, title).

### 2. Cấu hình filter

- `filters.news`: `enabled`, `currencies` (map từ symbol: EURUSD → [EUR, USD] — đặt trong
  instrument/profile, không hardcode), `min_impact` (default `high`),
  `window_before_min` / `window_after_min` (default 30/30).
- Ngữ nghĩa: tồn tại event impact ≥ min_impact, currency giao với currencies của symbol,
  và `clock.now ∈ [ts − before, ts + after]` → `passed=False`, blocking, reason khi chặn:
  giữ đúng reason hiện tại filter này đang emit qua §8 bước 3 (session/news gộp → kiểm code:
  nếu hiện là `wait` stage `session` thì tách stage `news_blackout` riêng, reason giữ nguyên).

### 3. Nạp vào Context

- Khi tạo run: snapshot các event trong khoảng thời gian của dataset vào bảng liên kết
  (`run_news_snapshot` hoặc chỉ cần cột `news_import_id` trên run + bảng import bất biến) —
  import file mới KHÔNG đổi run cũ. Context giữ list event đã sort; tra cứu O(log n)
  (searchsorted trên mảng ts).

### 4. UI

- Trang Config, mục filter news: ngoài toggle/params (schema tự render), thêm bảng nhỏ
  "sự kiện sắp tới trong dataset hiện tại" (`GET /api/news?from=&to=`) — read-only.

## Kiểm thử

- Unit: event EUR high tại T → decision tại T−15' bị chặn stage `news_blackout`,
  T−45' không chặn; min_impact=high bỏ qua event medium; symbol không liên quan currency
  không bị chặn.
- Integration: replay cùng dataset, có/không news import → hash đổi khi có event rơi vào
  vùng có signal (dựng fixture đảm bảo trúng); run cũ giữ nguyên hash sau khi import thêm file mới.

## Definition of done

- Import file lịch thật → bật filter → thấy decision bị chặn `news_blackout` đúng thời điểm;
  test/mypy/ruff xanh; decisions.md cập nhật mục News (format, ngữ nghĩa cửa sổ, snapshot per-run).
