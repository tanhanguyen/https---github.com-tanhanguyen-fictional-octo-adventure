# Plan 07 — Live paper trading: feed thời gian thực, recovery, cảnh báo

> Đọc trước: `plans/00-roadmap.md` (Bất biến). Phụ thuộc: plan 02 (feed abstraction), 03.
> Mục tiêu: bot chạy 24/7 trên dữ liệu thị trường **thật, thời gian thực**, khớp lệnh
> **giả lập** (paper) bằng chính order_engine hiện có. KHÔNG đặt lệnh thật (đó là plan 08).

## Quyết định cần USER chốt trước

1. **Venue đầu tiên — ĐÃ CHỐT (user, 2026-07-18)**: **Binance USDⓈ-M Futures** — crypto chỉ
   làm futures, KHÔNG spot. Docs user cung cấp:
   <https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account>.
   Market data: `GET https://fapi.binance.com/fapi/v1/klines?interval=15m` (symbol perpetual
   BTCUSDT/ETHUSDT) — công khai, không cần API key, bar 15m chuẩn UTC. **Testnet**
   `https://testnet.binancefuture.com` có cùng schema API → cùng một code chạy được cả demo
   realtime lẫn live, chỉ đổi base URL. Futures short tự nhiên → `ALLOW_SHORT=true` đúng nghĩa.
   Lưu ý paper: order_engine tự tính PnL theo giá, **không mô hình hoá funding fee** của
   perpetual — ghi deviation; số funding thật đối chiếu ở plan 08. Forex live: xem
   `plans/10-forex.md` (đề xuất OANDA v20 — có nến, không cần Windows/MT5).
   **VN30F**: user muốn hướng tới DNSE Entrade (docs <https://hdsd2.entrade.com.vn/entrade-api>),
   nhưng bộ API đó chỉ có giao dịch/tài sản, **không có endpoint nến OHLC** — live feed cho
   VN30F cần nguồn market data riêng (❓ user chỉ định nguồn; khi có thì viết `LiveFeed`
   thứ hai theo cùng interface, phần còn lại của plan không đổi).
2. ❓ Polling REST (mỗi phút kiểm bar 15m mới đóng) hay websocket? Đề xuất **polling** —
   đơn giản, đủ cho bar 15m, ít trạng thái lỗi.
3. ❓ Kênh cảnh báo: Telegram bot (token qua env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)?
4. **Quy tắc giữ lệnh theo khung — ĐÃ CHỐT (user, 2026-07-18)**, thay đề xuất
   weekend-flat cũ. Lưu khung thời gian vào lệnh (cột `trade.timeframe`, lấy từ config
   symbol lúc mở — để audit không phụ thuộc config đổi sau này) và áp dụng:
   - **TF ≤ H1** (15m, 1H — forex/crypto biến động mạnh): KHÔNG giữ qua cuối tuần
     (forex: force-close tại close bar cuối trước cửa sổ nghỉ, `trade_event` loại
     `weekend_close`, result phân loại bình thường; crypto chạy 24/7 nên không có cửa
     sổ nghỉ để đóng) và KHÔNG giữ quá 8 tiếng — `time_stop` 8h áp dụng **kể cả sau
     TP1** (deviation so C5 vốn tắt time-stop sau TP1 → ghi decisions.md).
   - **TF > H1** (H4, D1, …): được giữ qua cuối tuần và quá 8 tiếng — `time_stop` tắt.
   - Cơ chế: defaults suy từ `config.timeframe` lúc tạo run (per-symbol theo plan 04),
     vẫn override thủ công được qua config thường; VN H4/D1 rơi vào nhóm >H1 (khớp
     quyết định time-stop plan 05). Đóng cuối tuần phát alert `trade_closed` (plan 13).

## Nguyên tắc kiến trúc (không thương lượng)

- **Engine không đổi.** `main_loop`/`order_engine`/filters không biết mình đang live:
  vẫn nhận bar đã đóng + `Clock`. Toàn bộ "live" nằm ở tầng feed + runner mới.
- **Không wallclock trong engine** (bất biến #3): tầng live đọc wallclock, rồi `clock.set()`
  tới `close_ts` của bar vừa nhận — engine thấy thời gian y như replay.
- **Fill-at-next-open (D6) là lợi thế**: quyết định tại close bar t, paper-fill tại open bar t+1
  = giá open của bar tiếp theo lấy từ feed thật. Không cần tick data.

## Việc cần làm

### 1. `bot/data/live_feed.py` — LiveFeed (Binance Futures)

- Interface chung với feed hiện tại: trả DataFrame 15m chuẩn (open_ts UTC index, OHLCV)
  → đi qua `resample.build_all_timeframes` như mọi nguồn khác.
- Poll `GET /fapi/v1/klines?interval=…` — **interval lấy từ `config.timeframe` của run**
  (15m/1h/4h…), không hardcode 15m (quyết định 2026-07-18: forex/crypto khung tự do).
  Chỉ lấy bar **đã đóng**: bỏ phần tử cuối nếu `close_time > wallclock`; retry với
  backoff + jitter; timeout; lỗi mạng kéo dài → trạng thái `degraded`, cảnh báo, KHÔNG crash.
- Backfill khi khởi động: nạp đủ N bar lịch sử cho warmup indicator (EMA89 trên 1W cần nhiều
  nhất — tính đúng số bar 15m cần, đừng đoán) trước khi xử lý bar live đầu tiên.

### 2. `bot/engine/live_runner.py` — LiveRunner

- Vòng lặp: ngủ tới `next_bar_close + grace` (grace ~5s) → poll bar mới → nếu có:
  đăng ký bar, `clock.set(close_ts)`, chạy đúng chuỗi xử lý của Runner replay hiện tại
  (process fills → decide) → ghi DB như thường → lặp.
- **Idempotent theo bar_ts**: bar đã xử lý (có decision row với bar_ts đó trong run) → bỏ qua.
  Miss N bar (downtime) → xử lý tuần tự từng bar theo thứ tự cũ (catch-up), quyết định
  vẫn causal vì mỗi bar được xử lý với clock của nó.
- **Recovery sau restart**: run live có `mode='live'` trong bảng `run`; khởi động lại →
  tìm run live active, nạp open trades PENDING/OPEN từ DB, strategy state dựng lại bằng
  cách **re-run phần decide (không ghi)** trên K bar gần nhất hoặc persist state máy trạng thái
  retest vào DB mỗi bar — chọn persist state (bảng `strategy_state(run_id, symbol, json)`)
  vì re-run dễ lệch. Ghi quyết định này vào decisions.md.
- Một process riêng: `python -m bot.cli live --symbol BTCUSDT` (không chạy trong uvicorn worker;
  API đọc chung DB — WAL cho phép reader song song; API **không** ghi vào run live trừ
  lệnh dừng qua cờ trong DB (`run.stop_requested`) mà LiveRunner kiểm mỗi vòng).

### 3. Paper account & an toàn

- Tách DB live khỏi DB backtest: `backend/data/live.db` (đường dẫn theo env `BOT_DB_PATH`) —
  nghịch tay không làm hỏng lịch sử backtest.
- Config snapshot lúc tạo run live (như mọi run); đổi config → phải dừng và tạo run live mới
  (đơn giản, an toàn; hot-reload để sau).

### 4. Cảnh báo & quan sát

- `bot/notify.py`: Telegram gửi khi — trade mở/đóng (kèm R, equity), lỗi feed `degraded`/hồi phục,
  runner crash (systemd/launchd restart — xem plan 09), daily summary 1 tin/ngày.
  Không có token → log-only, mọi thứ vẫn chạy.
- API: `GET /api/live/status` — lag (wallclock − bar cuối), trạng thái feed, uptime;
  Dashboard hiện badge LIVE + lag.

## Kiểm thử

- LiveFeed test với HTTP mock (responses/httpx MockTransport): bar chưa đóng bị loại,
  backfill đủ warmup, retry hoạt động.
- LiveRunner test với FakeFeed đẩy bar theo kịch bản: catch-up sau miss 3 bar cho kết quả
  **giống hệt** replay cùng chuỗi bar (đây là test then chốt — live path và replay path
  phải cùng semantics); restart giữa chừng (dựng lại từ DB) → tiếp tục đúng.
- Không có test nào gọi mạng thật.

## Definition of done

- Chạy `bot.cli live` trên Binance testnet/mainnet market-data với account paper: sống qua
  ≥ 48h (hoặc demo bằng kịch bản fake dài), restart giữa chừng không mất/đúp lệnh,
  Telegram nhận thông báo; test/mypy/ruff xanh; decisions.md thêm mục Live semantics.
