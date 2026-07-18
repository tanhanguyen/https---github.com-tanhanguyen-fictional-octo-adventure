# Plan 10 — (Nâng cao) Forex: nguồn dữ liệu + venue, không cần Windows/MT5

> Đọc trước: `plans/00-roadmap.md` (Bất biến), `plans/07-live-paper.md`, `plans/08-broker-execution.md`.
> Phụ thuộc: plan 07 (LiveFeed/LiveRunner đã có); plan 08 nếu muốn đặt lệnh thật.
> Bối cảnh: user chạy macOS. Gói Python `MetaTrader5` **chỉ chạy trên Windows** (nó điều khiển
> terminal MT5 cài cùng máy) → MT5 không phải lựa chọn tự nhiên. Plan này đề xuất đường đi
> không cần Windows; MT5 chỉ là phương án dự phòng nếu user bắt buộc dùng broker MT5.

## Quyết định user phải chốt

1. ❓ **Venue forex — đề xuất: OANDA v20 REST API** (lý do ở dưới). Chốt thì các mục
   OandaFeed/OandaAdapter bên dưới thành việc làm; không thì dừng plan này lại.
2. ❓ Cặp tiền chạy live đầu tiên (code hiện có sẵn EURUSD — đề xuất giữ EURUSD).
3. ❓ Chạy practice bao lâu trước khi cân nhắc live (cùng tinh thần ❓3 của plan 08).

## Vì sao OANDA (so với MT5)

| | OANDA v20 REST | MT5 (gói `MetaTrader5`) |
|---|---|---|
| Hệ điều hành | Mọi OS (REST thuần) | **Chỉ Windows** |
| Demo realtime | fxTrade **Practice** — miễn phí, cùng schema API với live (đổi base URL + token) | Có, nhưng cần terminal Windows |
| Dữ liệu nến | **Có** — lịch sử + live cùng endpoint (giải quyết luôn data backtest) | Qua terminal |
| SL/TP server-side | Có (`stopLossOnFill`/`takeProfitOnFill`) | Có |
| Partial close | Có (close theo `units` lẻ) → TP1 50% map 1:1 | Có |

Nếu vẫn muốn MT5 (vì đã có tài khoản broker MT5): các cách chạy — (a) Windows VPS (phổ biến
trong giới forex, ~5–10 USD/tháng), (b) Wine/Docker trên macOS (mong manh, không khuyến nghị),
(c) máy Windows phụ chạy bridge nhỏ expose REST nội bộ cho bot. Chỉ chọn đường này khi có lý do
cụ thể; nếu không, OANDA đơn giản hơn hẳn.

Nguồn CSV backtest thay thế (không phụ thuộc venue, khớp plan 02): HistData.com (M1 miễn phí),
Dukascopy (tick). Nhưng nếu chốt OANDA thì lấy luôn nến lịch sử từ API cho đồng nhất.

## Cặp khuyến nghị theo phiên (user chốt 2026-07-18, đợt 3 — whitelist chống tương quan)

User chọn **giới hạn danh sách cặp được trade** (thay cho correlation check §6.7) theo
3 tiêu chí: thanh khoản, độ biến động, phiên hoạt động. Whitelist = mảng `symbols` của
plan 04 (enabled per-symbol), session windows per-symbol qua `overrides.filters.session`.
Giờ VN dưới đây là giờ mùa hè (DST); filter session đã tự xử lý DST theo D9.

| Symbol | Phiên | Lý do chọn | Lưu ý risk |
|---|---|---|---|
| **EURUSD** | London + NY (cả overlap) | Thanh khoản #1 thế giới, spread thấp nhất (~0.1–1 pip), biến động vừa (~60–80 pip/ngày) | Cặp chính, chuẩn risk-first |
| **GBPUSD** | London (~14:00–23:00 VN) | Thanh khoản cao, sôi động nhất phiên London | Biến động cao hơn (~90–120 pip/ngày), hay giật khi tin Anh; **tương quan +0.8÷0.9 với EURUSD — tránh mở cùng hướng cùng lúc** |
| **USDJPY** | NY (~19:00–04:00 VN) | Thanh khoản top 2–3, spread thấp, chạy theo lợi suất Mỹ | Tương quan thấp với EURUSD → đa dạng hoá tốt nhất trong nhóm |
| **USDCAD** | NY (~19:00–04:00 VN) | Sôi động giờ Mỹ (tin Canada 19:30 VN, dầu), spread ~1–2 pip | BUY EURUSD + SELL USDCAD = **cùng cửa "USD giảm"** — tính là cùng hướng USD |
| **XAUUSD** (vàng) | CHỈ overlap London–NY (~19:00–23:00 VN) | Thanh khoản rất cao trong overlap | Biến động lớn (có ngày 2–3%), spread rộng hơn forex nhiều → `overrides.risk.max_risk_per_trade_pct` = **NỬA mức forex**; chỉ bật sau khi 4 cặp forex chạy ổn; venue OANDA `XAU_USD` (Binance Futures không có vàng chuẩn) |

Quy tắc tay chống dồn cửa USD (chưa code — user tự giữ khi cấu hình, hoặc để trần
`max_total_open_risk_pct` đỡ): phân loại mỗi lệnh theo "hướng USD" (BUY EURUSD/GBPUSD/XAUUSD
= cửa USD giảm; BUY USDJPY/USDCAD = cửa USD tăng) — **tránh quá 2 lệnh cùng hướng USD
đồng thời**. Nếu sau này muốn engine tự chặn, đó là correlation check tuỳ chọn của §6.7
— cần user gật riêng trước khi thêm.

## Thiết kế (khi chốt OANDA)

Sonnet: xác minh mọi endpoint với docs chính thức
<https://developer.oanda.com/rest-live-v20/introduction/> trước khi code — chi tiết dưới đây
viết từ hiểu biết chung về v20, có thể lệch phiên bản.

- **Base URL**: practice `https://api-fxpractice.oanda.com`, live `https://api-fxtrade.oanda.com`
  — cùng schema, đổi base + token là xong (giống cặp testnet/prod của Binance).
- **Auth**: header `Authorization: Bearer <token>` (token tạo trong portal tài khoản; practice
  đăng ký miễn phí). Token qua env, quy tắc an toàn y hệt plan 08 (không vào DB/config/log).
- **Ký hiệu**: instrument dạng `EUR_USD` — thêm mapping symbol bot ↔ instrument OANDA
  (như mapping symbol ↔ perpetual của Binance).

### 1. `OandaFeed` — LiveFeed thứ hai (cùng interface plan 07)

- Nến: `GET /v3/instruments/EUR_USD/candles?granularity=M15&price=M` (mid). Tối đa ~5000
  nến/request → backfill warmup và cả import lịch sử cho backtest bằng cách paging theo `from`/`to`.
- Chỉ nhận bar `complete=true` (tương đương quy tắc "bỏ bar chưa đóng" của BinanceFeed).
- Lấy thêm `price=BA` (bid/ask) định kỳ → spread thực tế, dùng hiệu chỉnh `spread_pips`
  của backtest (plan 02) — trước giờ spread chỉ là con số đoán.
- **Lịch phiên**: forex đóng cửa cuối tuần (~Fri 17:00 NY → Sun 17:00 NY). LiveRunner phải
  biết lịch này: không bar mới trong khoảng đó là BÌNH THƯỜNG, không phải feed `degraded`.
  Engine không đổi — C3 rollover 17:00 NY đã có sẵn.

### 2. `OandaAdapter` — ExecutionAdapter (plan 08), nếu đặt lệnh thật

- Vào lệnh (map D6): `POST /v3/accounts/{accountID}/orders` body
  `{order: {type: "MARKET", instrument, units, stopLossOnFill, takeProfitOnFill}}` —
  `units` dương = Long, âm = Short; 1 lot chuẩn = 100_000 units → map từ lot của bot.
  SL/TP gắn ngay lúc vào lệnh, server-side (bot chết SL vẫn sống) — gọn hơn Binance
  (không cần cặp lệnh rời + hủy chéo).
- Dời BE: `PUT /v3/accounts/{id}/trades/{tradeID}/orders` cập nhật `stopLoss`.
- TP1 partial 50%: `PUT /v3/accounts/{id}/trades/{tradeID}/close` với `units` = 50%
  → map 1:1 mô hình bot, không đè `partial_fraction`.
- Reconciliation: `GET /v3/accounts/{id}/openTrades` so với bảng `trade` OPEN (cùng khuôn
  plan 08); `fill_price_broker` từ transaction fill.
- **Swap/financing**: OANDA tính phí qua đêm trên vị thế giữ — paper không mô hình hoá
  (cùng loại deviation với funding fee Binance); số thật đọc từ transactions
  (`DAILY_FINANCING`) → vào báo cáo so lệch paper-vs-real của plan 08.

### 3. Ghi chép

- `docs/decisions.md`: deviation "swap/financing không mô hình hoá trong paper" + mapping
  units↔lot + nguồn spread thực nghiệm.

## Kiểm thử

- OandaFeed test với HTTP mock (như BinanceFeed): loại bar `complete=false`, paging backfill
  đủ warmup, lịch cuối tuần không sinh cảnh báo degraded.
- OandaAdapter test trên **practice** (tương đương Binance testnet trong plan 08);
  không test nào gọi mạng thật trong CI.
- Test then chốt của plan 07 giữ nguyên: live path ≡ replay path trên cùng chuỗi bar.

## Definition of done

- `bot.cli live --symbol EURUSD` chạy trên practice ≥ 1 tuần (qua ít nhất 1 cuối tuần để
  chứng minh lịch phiên đúng), restart không mất/đúp lệnh; nếu làm adapter: demo practice
  theo tiêu chí plan 08 (reconciliation, kill switch, báo cáo slippage + financing).
