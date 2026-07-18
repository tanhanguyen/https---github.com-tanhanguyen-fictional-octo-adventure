# Plan 05 — Profile chứng khoán VN: STOCK_VN_CASH + STOCK_VN_DERIV

> Đọc trước: `plans/00-roadmap.md` (Bất biến) + mục "Phase 2" cuối `README.md` và
> `docs/decisions.md` (D9/D10/D11, deviation #11/#12). Phụ thuộc: plan 04 (profile per-symbol).
> §7 spec viết cho chứng khoán Mỹ — KHÔNG port thẳng. Nhiều điểm cần user chốt (đánh dấu ❓).

## Phạm vi

Hai symbol_type mới hoạt động đầy đủ trong backtest (dữ liệu CSV do user cung cấp):

- `STOCK_VN_CASH` — cổ phiếu HOSE, ví dụ HPG/FPT. D1 là timeframe chính.
- `STOCK_VN_DERIV` — hợp đồng tương lai VN30F1M.

## Việc cần làm

### 1. Nền chung cho cả hai

- **Timeframe — user chốt 2026-07-18**: chứng khoán phái sinh VN giao dịch khung **H4/D1**
  (cổ phiếu cash vốn đã D1). Config `timeframe` đã hỗ trợ `4H`/`1D`; per-symbol qua
  `overrides.timeframe` của plan 04.
  - ❓ Chọn khung **mặc định** cho profile VN30F: đề xuất **D1** (ít lệnh, ít nhiễu,
    hợp mục tiêu ít-lỗ-ít-sự-cố của user; H4 là biến thể thử qua backtest so sánh).
  - **Định nghĩa bar H4 trên phiên VN** (phiên chỉ ~4.5h/ngày): resample lưới 4H theo UTC
    sẽ cắt phiên rất lệch → ❓ đề xuất **neo origin 09:00 Asia/Ho_Chi_Minh** (bar 09:00–13:00
    và 13:00–15:00 ICT, khớp cách các nền tảng chart VN hay hiển thị) — cần tham số
    `resample_origin` theo profile trong `build_all_timeframes`. Nếu user không muốn phức tạp:
    chỉ dùng D1, khỏi định nghĩa H4 (đơn giản nhất). Bar D1 an toàn: cả phiên VN nằm gọn
    trong một ngày UTC (02:00–07:45 UTC) nên lưới UTC và lưới ICT cho cùng kết quả — có test.
  - **MTF khi lên khung cao**: 4H → xác nhận 1D; 1D → xác nhận **1W**. EMA89 trên 1W cần
    ~89 tuần dữ liệu (~2 năm) mới hết warmup — kiểm độ dài CSV user cung cấp trước khi chạy,
    thiếu thì filter theo C12 trả `wait/warmup` (đúng thiết kế, nhưng phải báo user rõ).
- **Phiên**: 09:00–11:30 + 13:00–14:30 Asia/Ho_Chi_Minh (D9 đã định nghĩa — kiểm filter
  `session` hỗ trợ 2 khoảng/ngày; hiện London+NY cũng là 2 khoảng nên khả năng đã chạy, cần test).
- **Trading day**: KHÔNG dùng rollover 17:00 NY (D10) — trading day = ngày lịch
  Asia/Ho_Chi_Minh. `trading_day()` nhận tham số hoá theo symbol_type (rollover_tz/time
  từ profile; VN: rollover 00:00 Asia/Ho_Chi_Minh).
- **Limits**: `MAX_CONCURRENT_TRADES=2`, daily-loss-limit **tắt** (D10 — filter
  `account_risk` phần daily bị disable theo profile, decision vẫn ghi
  `enabled=false` cho minh bạch).
- **Time stop — ĐÃ CHỐT** theo quy tắc giữ-lệnh-theo-khung (user 2026-07-18, chi tiết
  plan 07 §4): H4/D1 thuộc nhóm TF > H1 → `time_stop` **tắt** cho stock VN, được giữ
  lệnh qua cuối tuần.
- **DXY filter**: không áp dụng cho VN (spec §6.6 là forex) — profile mặc định `dxy.enabled=false`.
- **InstrumentSpec mới** trong `instruments.yaml`:
  - Cổ phiếu: lô 100 cp, tick theo bảng giá HOSE (❓ đơn giản hoá: tick 50đ dưới 10k /
    100đ 10–50k / 500đ trên 50k — hay bỏ qua tick, dùng giá CSV thô? Đề xuất: bỏ qua tick
    trong backtest, ghi deviation);
  - VN30F: multiplier 100.000 VND/điểm, lot 1 HĐ, tick 0.1 điểm.
  - `risk_manager.calculate_lot` phải ra **số nguyên lô** (100 cp) / số nguyên HĐ —
    floor, tối thiểu 1 lô nếu risk cho phép, không thì bỏ lệnh (reason `no_confirm`?
    KHÔNG — đây là account risk: emit `daily_loss_limit_reached` sai nghĩa; đề xuất:
    stage `lot_below_min` dưới reason `max_concurrent_trades_reached` cũng sai.
    **Chốt thiết kế**: dùng reason `wait`, stage `lot_below_min`, detail giải thích —
    ghi vào decisions.md như deviation mới. ❓ user xác nhận).
  - Tiền tệ tài khoản VND ↔ account USD hiện tại: ❓ đề xuất tài khoản VND riêng khi
    symbol_type là stock VN (STARTING_EQUITY_VND trong profile), không mix VND/USD một tài khoản.

### 2. STOCK_VN_CASH

- **ALLOW_SHORT=false** (deviation #12): signal SELL sinh ra nhưng bị chặn —
  emit reason `no_signal`, stage `allow_short`, detail "SELL blocked: cash market".
  (Giữ từ vựng §8; `no_signal` chọn vì với thị trường này signal SELL coi như không tồn tại.)
- **T+2.5**: cổ phiếu mua ngày T chỉ bán được từ phiên chiều T+2 (thực tế VN hiện hành:
  hàng về chiều T+2). Engine: lệnh mở (BUY) không được phép đóng (SL/TP/exit) trước mốc
  phiên chiều của ngày giao dịch thứ 2 sau entry. Trong khoảng chưa được bán: SL/TP
  **không kích hoạt** — chỉ ghi `trade_event` loại `exit_suppressed_settlement` khi giá
  chạm mức, để backtest trung thực với rủi ro thật. ❓ user xác nhận mô hình này
  (thay thế: vẫn cho đóng, chấp nhận sai lệch — không khuyến nghị).
- Giá tham chiếu ±7% trần/sàn HOSE ảnh hưởng khớp gap: ❓ Phase này bỏ qua (ghi deviation),
  trừ khi user muốn mô phỏng.

### 3. STOCK_VN_DERIV (VN30F1M)

- **Đáo hạn**: thứ Năm tuần thứ 3 hàng tháng. Engine phải **force-close** vị thế mở tại
  close phiên ngày đáo hạn (trade_event `expiry_close`, result phân loại bình thường F2).
  Hàm `vn30f_expiry(year, month)` trong `core/timeframes.py` + test các tháng có ngày lễ
  (chỉ tính thứ Năm tuần 3 theo lịch, không xử lý nghỉ lễ — ghi deviation ❓).
  Khi chạy live (plan 07/08): lịch đáo hạn **thật** lấy được từ DNSE Entrade API —
  `GET https://services.entrade.com.vn/entrade-api/derivatives` trả các mã đang giao dịch
  kèm `expirationDate` (docs: <https://hdsd2.entrade.com.vn/entrade-api>, endpoint không cần
  auth theo docs) — đối chiếu với hàm tính, lệch thì tin API.
  Lưu ý: API này **không có** dữ liệu nến lịch sử — backtest vẫn cần CSV do user cung cấp.
- **Chuỗi giá liên tục**: dữ liệu do user cung cấp. ❓ User chốt: (a) dùng chuỗi đã
  back-adjust sẵn (khuyến nghị — script `scripts/stitch_vn30f.py` nhận các file hợp đồng
  riêng lẻ + lịch roll, xuất chuỗi back-adjusted, là công cụ ngoài engine); hay (b) engine
  xử lý roll runtime (phức tạp, không khuyến nghị cho backtest).
- Short OK; margin không mô phỏng (risk theo `MAX_RISK_PER_TRADE` như spec) — ghi deviation.

### 4. Kiểm thử

- Fixture CSV D1 nhỏ dựng tay cho: chặn SELL cash; T+2.5 giữ lệnh qua 2 ngày (giá chạm SL
  ngày T+1 → suppressed, thoát khi được phép); lô nguyên (equity nhỏ → lot_below_min);
  VN30F force-close ngày đáo hạn; phiên 2 khoảng VN; trading day không rollover NY.
- Golden run cho mỗi symbol_type mới trên fixture cố định.

## Definition of done

- Backtest chạy hết trên một CSV cổ phiếu + một CSV VN30F (user cung cấp hoặc fixture),
  mọi hành vi ❓ đã được user chốt và ghi thành deviation đánh số tiếp theo trong
  `docs/decisions.md`; test/mypy/ruff xanh.
- **Trước khi code, Sonnet phải đưa danh sách ❓ ở trên cho user chốt** — đừng tự quyết
  các điểm nghiệp vụ thị trường VN.
