# Plan 01 — Stabilize: commit fix, trả nợ kỹ thuật, A/B harness, CI

> Đọc trước: `plans/00-roadmap.md` (mục "Bất biến" áp dụng nguyên văn cho plan này).
> Không thêm tính năng mới trong plan này — chỉ củng cố những gì đã có.

## Bối cảnh

Working tree đang có thay đổi chưa commit:

- `backend/src/bot/api/run_service.py` — thêm decorator `_locked` serialize mọi method đụng
  `self.conn` qua `self.lock` (RLock). Lý do: một `sqlite3.Connection` dùng chung giữa worker
  thread (play) và request threads đã từng corrupt DB — bằng chứng là file
  `backend/data/runtime.db.corrupt.bak`.
- `README.md` (mới) và `backend/data/` (runtime DB, không nên track).

`docs/decisions.md` mục "Quyết định phát sinh trong Phase 2/3" ghi nhận 2 nợ kỹ thuật có chủ đích
mà plan này trả:

1. **Lot size chốt lúc quyết định** dùng entry ước lượng `close[-1]` — dự định gốc (deviation #7)
   là chốt lúc **khớp** với entry thật.
2. **`INTRABAR_PRIORITY="path"` là xấp xỉ** — chọn mốc gần `open` hơn thay vì đọc sub-bar path
   15 bước thật đã sinh trong `synthetic.py`.

## Việc cần làm

### 1. Dọn và commit thay đổi đang treo

- Trong `run_service.py`: khối `_locked` hiện được định nghĩa **chen giữa các import**
  (các `from bot.…` import nằm sau code) → vi phạm E402. Dời toàn bộ import lên đầu file,
  decorator xuống sau. Giữ nguyên semantics.
- Rà lại: **mọi** method của `RunnerService` đụng `self.conn` hoặc state mutable
  (`run_id`, worker) phải có `@_locked` hoặc tự cầm lock (đặc biệt `step/play/pause/reset/create_run`
  nếu chưa). Một test mới: chạy `play(interval_ms nhỏ)` song song với vòng lặp gọi
  `account_snapshot()/list_decisions()` từ nhiều thread trong ~2s, không exception, DB
  `PRAGMA integrity_check` trả `ok`.
- `.gitignore`: bổ sung `backend/data/` (nếu chưa). Xoá `backend/data/runtime.db.corrupt.bak`
  (đã hiểu nguyên nhân, không cần giữ).
- Commit: fix thread-safety + README + .gitignore.

### 2. Nợ kỹ thuật #1 — lot chốt lúc khớp

- Chuyển lời gọi `risk_manager.calculate_lot` từ `main_loop.decide` vào
  `OrderEngine.process_bar` nhánh fill `PENDING`, dùng `entry` thật vừa fill
  (`sl_distance = |entry − sl|`). `OpenTrade` lúc quyết định mang đủ input cho việc tính
  (risk %, risk_multiplier từ equity_curve, sl) nhưng `lot_size` chỉ có sau fill.
- Decision log: giá trị lot ở decision row (nếu đang log) đổi thành "estimated" hoặc bỏ —
  chọn cách ít phá schema nhất, ghi chú trong `docs/decisions.md`.
- Risk thực tế mỗi lệnh phải đúng `MAX_RISK_PER_TRADE × risk_multiplier` theo entry thật —
  thêm assert trong `test_order_engine.py` (case có gap mở nến để entry ≠ close[-1]).
- Hash golden sẽ đổi → re-pin theo đúng thủ tục ở roadmap.

### 3. Nợ kỹ thuật #2 — path priority dùng sub-bar path thật

- `synthetic.py` đã sinh 15 sub-step cho mỗi bar 15m; truyền path này xuống
  `OrderEngine.process_bar` (tham số tuỳ chọn `sub_path: Sequence[float] | None`).
  Khi `INTRABAR_PRIORITY="path"` và có path: duyệt tuần tự các mức giá sub-step, mốc nào
  (SL hay TP) bị chạm trước thì thắng. Không có path (CSV thật) → fallback về xấp xỉ hiện tại,
  docstring nói rõ.
- Cập nhật test `test_sl_and_tp_same_bar_path_priority_differs_from_sl_first` + thêm case
  path thật cho kết quả khác xấp xỉ.
- Lưu ý: resample lên 1H/4H thì path của các bar 15m con nối lại là path của bar lớn —
  chỉ cần làm cho timeframe chạy chính; nếu phức tạp quá thì chỉ hỗ trợ khi TIMEFRAME="15m"
  và ghi giới hạn vào decisions.md (chấp nhận được).

### 4. A/B filter harness — chứng minh không có toggle chết

- CLI mới: `python -m bot.cli ab --bars 5000 --seed 42` — với **từng** filter trong registry
  (trừ `atr_ref` locked): chạy baseline (config default) và biến thể (filter đó đảo trạng thái
  enabled), so `decision_stream_hash` + số lệnh. In bảng: filter | hash đổi? | Δ số lệnh.
- Test integration `test_ab_filters.py` (đánh dấu `@pytest.mark.slow`): với seed/bars cố định,
  assert **ít nhất** các filter sau làm hash đổi khi toggle: `confirmation_lag`, `session`,
  `mtf`, `adx`, `er`, `trend`. Các filter hiếm kích hoạt trên synthetic (`news` vốn off,
  `dxy`, `volume` off cho FOREX, `atr_zscore`, `equity_curve`, `range_width`, `wick`,
  `account_risk`, `time_stop`) — nếu hash không đổi thì harness in cảnh báo chứ không fail,
  nhưng phải có **unit test dựng tay** chứng minh từng filter chặn/điều chỉnh đúng
  (kiểm tra `tests/unit/test_filters.py` đã phủ chưa, bổ sung chỗ thiếu).

### 5. CI — GitHub Actions

- `.github/workflows/ci.yml`: job backend (Python 3.10: `pip install -e ".[dev]"`,
  `pytest -q` không gồm `slow`, `mypy src`, `ruff check src`) + job frontend
  (`npm ci && npm run build`). Chạy trên push + PR.

## Definition of done

- Working tree sạch, mọi thứ trên đã commit theo từng bước logic.
- `pytest -q`, `mypy src` strict, `ruff check src` đều xanh; golden hash mới đã pin và
  ghi chú trong `docs/decisions.md` (xoá 2 mục nợ kỹ thuật tương ứng, thay bằng mô tả giải pháp).
- `python -m bot.cli ab` chạy được, bảng kết quả không có filter "chết" ngoài danh sách
  đã giải thích.
- CI xanh trên GitHub (nếu repo chưa có remote thì file workflow vẫn phải hợp lệ —
  kiểm bằng `act` không bắt buộc).
