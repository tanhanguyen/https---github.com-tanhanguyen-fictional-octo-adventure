# Plan 08 — (Tuỳ chọn) Đặt lệnh thật qua broker

> Đọc trước: `plans/00-roadmap.md`, `plans/07-live-paper.md`. Phụ thuộc: plan 07 chạy ổn ≥ 2 tuần.
> **Plan này CHƯA thực hiện được cho tới khi user chốt broker và ký các quyết định rủi ro
> bên dưới.** Sonnet: nếu được giao file này mà chưa có câu trả lời ❓, dừng lại hỏi trước.
>
> **Prerequisite bổ sung cho CRYPTO FUTURES (user chốt 2026-07-18, đợt 3):**
> (a) **KHÔNG được arm mode `real` cho crypto futures khi mục 12b (margin/liquidation
> guard, `plans/12-execution-realism.md`) chưa xong** — với futures đây là phanh an toàn
> bắt buộc, không phải "độ thật tăng thêm"; đưa vào chính danh sách hard-caps kiểm trước
> `place_market` bên dưới. (b) Kết quả **paper crypto khung H4/D1** (giữ lệnh nhiều ngày
> = ăn funding nhiều kỳ) chỉ được dùng làm căn cứ sang real **sau khi 12a (funding fee)
> xong** và chạy lại paper/backtest có funding.

## Quyết định user phải chốt

1. Broker/venue — **đã chốt**: (a) crypto = **Binance USDⓈ-M Futures** (chỉ futures,
   KHÔNG spot — user chốt 2026-07-18, làm ĐẦU TIÊN vì testnet demo realtime + live cùng
   một API; xem mục "BinanceFuturesAdapter"); (b) phái sinh VN = **DNSE Entrade API**
   (xem mục "EntradeAdapter"). ❓ Còn lại: forex — user không có Windows nên MT5 khó chạy;
   đề xuất **OANDA v20** thay thế (REST mọi OS, practice + live cùng schema, có cả nến) —
   chi tiết + quyết định ở `plans/10-forex.md`.
2. ❓ Giới hạn cứng còn chờ: max lot/lệnh, max lệnh/ngày. **Drawdown TỔNG từ đỉnh
   equity — CẬP NHẬT (user 2026-07-18, đợt 3, thay quyết định đợt 2)**: **WARN tại 5%**
   chỉ alert; **CRITICAL tại 10% → TỰ CHUYỂN PAPER** — dùng chung cơ chế circuit
   breaker/arming: chặn mọi lệnh real mới, vị thế đang mở KHÔNG bị đóng ép (SL/TP
   server-side vẫn quản tới khi đóng — cùng semantics với daily-loss-limit "chỉ chặn
   lệnh mới"), muốn real lại phải arming thủ công. Cả hai mốc phát qua alert center
   plan 13 (Telegram + toast web + log DB), code `drawdown_warn`/`drawdown_critical`.
3. ❓ Tài khoản demo trước bao lâu rồi mới sang real.
4. **Risk giai đoạn real đầu — ĐÃ CHỐT (user 2026-07-18)**: bắt đầu **0.5%**/lệnh
   (`max_risk_per_trade_pct` = % equity mất nếu lệnh chạm SL; equity_curve filter vẫn
   nhân giảm tiếp khi thua chuỗi). Sau 1–2 tuần chạy ổn, user TỰ nâng qua Config UI
   (config versioned — mỗi lần đổi đều có vết, không hard-code lịch nâng). User dự
   kiến nâng tới 2%/lệnh — worst-case ngày khi đó = 3 lệnh × 2% = 6% (trần tổng danh
   mục đã chốt là optional, default tắt — xem plan 04).

## Thiết kế (phần chốt được trước, không phụ thuộc broker)

### ExecutionAdapter interface — `bot/execution/base.py`

- `place_market(symbol, direction, lot, sl, tp) -> BrokerOrder`
- `modify_sl(order_id, new_sl)` (dời BE), `close_partial(order_id, fraction)` (TP1 50%),
  `close_all(order_id)`, `positions() -> list[BrokerPosition]`
- Các implementation: `PaperAdapter` (bọc order_engine hiện tại — mặc định, hành vi
  plan 07 không đổi), `BinanceFuturesAdapter` (làm đầu tiên), `EntradeAdapter` (VN30F).
- LiveRunner gọi adapter tại đúng các điểm order_engine hiện fill/close; semantics quyết định
  KHÔNG đổi — chỉ thay "ai khớp lệnh".

### An toàn nhiều lớp (bắt buộc, code trước adapter thật)

- **Arming**: mặc định `EXECUTION_MODE=paper`. Sang `real` đòi hỏi ĐỒNG THỜI: env
  `BOT_EXECUTION=real`, cờ trong config version active, và file `data/ARM_REAL` tồn tại —
  thiếu một thứ → paper + cảnh báo. Không có đường bật `real` qua API.
- **Kill switch**: `POST /api/live/kill` + lệnh Telegram `/kill` → đóng mọi vị thế qua adapter,
  chuyển paper, đòi arming lại thủ công.
- **Reconciliation** mỗi vòng: `adapter.positions()` vs bảng `trade` OPEN — lệch (đóng tay
  trên sàn, partial fill lạ) → đánh dấu trade `desynced`, cảnh báo, KHÔNG tự sửa kép.
- **Hard caps** (❓2) kiểm ngay trước `place_market`, độc lập với filters — đây là phanh
  cuối cùng, không phụ thuộc logic chiến lược.
- API key: env-only, không bao giờ vào DB/config/log; quyền key tối thiểu (trade, KHÔNG withdraw).

### Chống sự cố khớp lệnh (bắt buộc, áp cho MỌI adapter thật)

Ưu tiên user (2026-07-18): ít lỗ nhất, ít sự cố nhất, lời ít cũng được — các quy tắc dưới
đây chọn phương án "thà bỏ lỡ / thà chịu phí" thay vì "ôm rủi ro hở":

1. **Idempotent theo clientOrderId**: mọi lệnh gửi sàn mang id deterministic
   `{run_id}-{symbol}-{bar_ts}-{leg}` (entry/sl/tp1/tp2…). Retry sau timeout/crash:
   query theo id đó trước — đã tồn tại thì KHÔNG gửi lại. Đây là lá chắn chống đúp lệnh
   khi mạng chập chờn (Binance: `newClientOrderId`; Entrade: kiểm docs, không có thì
   tra sổ lệnh theo thời gian + symbol trước khi gửi lại).
2. **Không để vị thế trần (không SL)**: sau khi MARKET fill, đặt SL ngay lập tức;
   đặt SL thất bại sau N retry (đề xuất 3 lần trong ~10s) → **đóng vị thế ngay bằng
   MARKET** + cảnh báo Telegram. Mất phí một vòng còn hơn một vị thế không phanh.
3. **Partial TP vs bước khối lượng**: nếu `partial_fraction < 1`, ngay lúc sizing yêu cầu
   lot ≥ 2 × bước khối lượng (stepSize/lô) để nửa lệnh không tròn về 0; không đạt →
   bỏ lệnh (đi đường `wait`/`lot_below_min` của plan 05) — nhất quán ưu tiên ít-lỗ,
   không âm thầm đổi sang đóng-full.
4. **Boot check**: khởi động ở mode real → chạy reconciliation TRƯỚC khi xử lý bar đầu tiên;
   sàn có vị thế/lệnh mà DB không biết (hoặc ngược lại) → `desynced`, KHÔNG vào lệnh mới
   cho tới khi user xử lý tay. Không bao giờ "tự dọn" vị thế lạ.
5. **Circuit breaker lỗi API**: N lỗi đặt-lệnh liên tiếp (đề xuất 3) hoặc lỗi
   reconciliation lặp lại → tự chuyển paper + cảnh báo, đòi arming lại thủ công
   (dùng chung cơ chế kill switch). Sự cố sàn/mạng kéo dài thì bot đứng ngoài chợ.
6. **Một nguồn chân lý về SL/TP**: SL/TP server-side trên sàn là chính; bot không tự
   "khớp SL trong đầu" rồi gửi lệnh đóng chồng lên — tránh double-close khi cả hai
   cùng kích hoạt. Order_engine ở mode real chỉ **quan sát** fill từ sàn (qua
   reconciliation) chứ không tự fill.

### Khớp lệnh thật ≠ mô hình D6

- Market order khớp ~ngay sau close bar t, không phải đúng open bar t+1; slippage thật.
  Ghi `fill_price_broker` cạnh `fill_price_model`, report so lệch (slippage thực nghiệm) —
  dùng để hiệu chỉnh `slippage_pips` của backtest (plan 02).
- SL/TP: đặt server-side trên sàn chứ không chỉ trong bot — bot chết thì SL vẫn sống.
  (Binance Futures KHÔNG có OCO — dùng cặp lệnh reduce-only, xem mục BinanceFuturesAdapter.)
  Dời BE/TP1 = modify/cancel-replace các lệnh đó.

### BinanceFuturesAdapter — crypto USDⓈ-M Futures (làm đầu tiên)

Docs (user cung cấp):
<https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account>.
REST base PROD `https://fapi.binance.com`, **TESTNET** `https://testnet.binancefuture.com` —
cùng schema, đổi base URL + key testnet là chạy demo realtime (giai đoạn ❓3 chạy testnet).

- **Auth**: API key + chữ ký HMAC-SHA256 (timestamp + recvWindow) trên request có ký;
  key qua env, quyền tối thiểu (Enable Futures, KHÔNG withdraw), khuyến nghị IP whitelist.
- **Khởi động**: `GET /fapi/v1/exchangeInfo` → `stepSize`/`minQty`/precision để làm tròn lot;
  set **one-way position mode** (không hedge mode — khớp mô hình 1 trade/symbol của bot);
  set margin type (đề xuất ISOLATED ❓) + leverage (`POST /fapi/v1/leverage`) — lot vẫn do
  `MAX_RISK_PER_TRADE` của bot quyết, leverage chỉ là trần margin → đề xuất thấp 3–5x
  (❓ user chốt) để xa mức liquidation.
- **Vào lệnh (map D6)**: `POST /fapi/v1/order` `type=MARKET` ngay sau close bar; lấy
  `avgPrice` + `commission` (từ response/`GET /fapi/v1/userTrades`) → `fill_price_broker` + phí thật.
- **SL/TP server-side**: đặt 2 lệnh reduce-only sau khi vào: `STOP_MARKET` (SL) +
  `TAKE_PROFIT_MARKET` (TP); một lệnh khớp → hủy lệnh kia (vòng reconciliation đảm nhiệm).
  Dời BE = cancel + đặt lại STOP_MARKET giá mới.
- **TP1 partial 50%**: `TAKE_PROFIT_MARKET` `reduceOnly=true` với quantity = 50% (làm tròn
  stepSize); khớp xong → đặt lại SL (BE) cho phần còn lại. Khớp mô hình partial của bot 1:1 —
  không phải đè `partial_fraction` như trường hợp Entrade.
- **Reconciliation**: `GET /fapi/v2/positionRisk` (vị thế) + `GET /fapi/v1/openOrders`
  (các lệnh SL/TP kỳ vọng) so với bảng `trade` OPEN.
- **Funding fee**: paper không mô hình hoá; số thật đọc `GET /fapi/v1/income`
  (`incomeType=FUNDING_FEE`) → đưa vào báo cáo so lệch paper-vs-real, ghi deviation.

### EntradeAdapter — phái sinh VN qua DNSE Entrade API

Docs: <https://hdsd2.entrade.com.vn/entrade-api> (mỗi trang có bản `.md` — thêm `.md` vào URL;
index đầy đủ: `https://hdsd2.entrade.com.vn/llms.txt`). Những gì đã xác minh từ docs:

- **Hai môi trường**: PROD `https://services.entrade.com.vn/entrade-api/…` và
  **PAPERTRADE** `https://services.entrade.com.vn/papertrade-entrade-api/…` (ít nhất cho
  đặt lệnh) — giai đoạn demo (❓3) chạy trên papertrade, khớp đúng triết lý plan này.
- **Auth**: `POST /entrade-api/v2/auth` body `{username, password}` → JWT dùng cho mọi API,
  **hạn 8 tiếng** → adapter phải tự re-login trước hạn (refresh ở ~7h hoặc khi 401);
  credentials qua env, như quy tắc API-key ở trên. Lưu ý quy tắc an toàn chung: bot đọc
  credentials từ env do user tự đặt, không bao giờ ghi vào DB/config/log.
- **Danh sách mã + đáo hạn**: `GET /entrade-api/derivatives` trả các mã đang giao dịch
  (`VN30F1M/2M/1Q/2Q`) kèm `expirationDate`, giá trần/sàn/tham chiếu — dùng cho:
  (a) chọn hợp đồng F1M hiện hành khi đặt lệnh; (b) đối chiếu lịch đáo hạn với hàm
  `vn30f_expiry` của plan 05; (c) kiểm giá đặt nằm trong trần/sàn trước khi gửi.
- **Đặt lệnh**: `POST /entrade-api/derivative/orders` — body gồm `symbol`, `price`,
  `orderType` (`LO/MTL/ATC/ATO/MAK/MOK`), `side` (`NB`=Long, `NS`=Short), `quantity`,
  `investorId`, `bankMarginPortfolioId` (id gói vay — lấy từ endpoint gói vay lúc khởi động).
  Map D6 "fill at open": đặt `MTL` ngay sau bar đóng. Response có `orderStatus`,
  `averagePrice`, `tradingFee/tradingTax` → ghi `fill_price_broker` + phí thực.
- **SL/TP server-side**: có sẵn cơ chế cắt lỗ/chốt lời theo **deal** (endpoints 12–15:
  lấy/sửa cấu hình cắt lỗ, đóng deal, chốt lời-cắt lỗ từng deal) — map: SL/BE của bot →
  sửa cấu hình cắt lỗ deal; TP1 partial 50% → kiểm xem API cho đóng một phần deal
  (đóng `quantity` lẻ) hay không; nếu không hỗ trợ partial → đè config
  `partial_fraction=1.0` cho profile này và ghi deviation (❓ user chốt).
- **Sổ lệnh/deals**: endpoints 8–11 (sổ lệnh, chi tiết, hủy, danh sách deals) → nguồn cho
  reconciliation mỗi vòng.
- **KHÔNG có endpoint nến/OHLC** trong bộ docs này — nhưng câu hỏi đó **đã đóng**
  (2026-07-23): market data cho live runner lấy từ **DNSE OpenAPI**
  (<https://developers.dnse.com.vn>, `GET /price/ohlc` + WS `ohlc_closed`), đã triển khai ở
  `bot/data/dnse_feed.py`. EntradeAdapter chỉ lo khớp lệnh.
  *Cân nhắc khi làm plan 08*: DNSE OpenAPI **cũng có** API đặt lệnh (`/docs/dnse/trading`,
  2FA bằng Trading Token 8 giờ qua Email/Smart OTP, xác thực HMAC cùng cơ chế signature như
  market data) — nếu dùng nó thay Entrade thì market data và execution chung một bộ
  credentials, đỡ một hệ thống phải nuôi. ❓ để user chốt khi bắt đầu plan 08.
- OTP/2FA: docs không nhắc cho luồng v2/auth — xác minh thực nghiệm trên papertrade;
  nếu tài khoản thật đòi OTP đặt lệnh thì phải xử lý (❓ hỏi user khi gặp).

## Kiểm thử

- Adapter test trên môi trường giả lập của broker (Binance **Futures testnet**;
  Entrade **papertrade**); PaperAdapter phải cho
  kết quả giống hệt plan 07 (regression). Arming/kill/reconciliation có test riêng với
  adapter mock trả tình huống lệch vị thế.

## Definition of done

- Chạy demo/testnet ≥ 2 tuần: lệnh mở/đóng khớp giữa sàn và DB, kill switch đã diễn tập,
  báo cáo slippage thực nghiệm; user nghiệm thu bằng mắt trước khi cân nhắc tiền thật.
