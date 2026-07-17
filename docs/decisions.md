# Quyết định kỹ thuật — nguồn chân lý khi mâu thuẫn với spec

Spec: [`spec_v1_2.md`](spec_v1_2.md). Khi tài liệu này và spec mâu thuẫn, **tài liệu này thắng** —
mỗi sai lệch đều có lý do ghi kèm. Mỗi quy ước C* có test canh.

## Quyết định đã chốt (D1–D11)

| # | Quyết định | Ghi chú |
|---|---|---|
| D1 | Spec = **V1.2** | Nguồn chân lý duy nhất (V1.3 không tồn tại) |
| D2 | **Một bộ tham số duy nhất** — bỏ bảng §7 | SL Breakout = `Range_Low − 0.5×ATR(14)` (§6.8/§8, không phải 1.5×ATR của §7); ER range = 0.3. `SYMBOL_TYPE=FOREX`, `TIMEFRAME=1H`. Per-asset profile để Phase 2 (§11.1) |
| D3 | **Xoá `ADVANCED_FILTER_MODE`** | 16 bộ lọc toggle độc lập (xem mapping bên dưới). `RANGE_WIDTH_ATR_MULT=1.5`, `confirmation_lag.enabled=true` áp cho cả hai chiến lược |
| D4 | Wick = `WICK_MIN_RATIO = 0.5` | `wick_ngược ÷ (High−Low) ≥ 0.5`; High==Low → ratio 0. Spec cho ngữ nghĩa, không cho số |
| D5 | **Retest theo ATR** | `RETEST_TOLERANCE_MODE="atr"`, mult 0.25. §9 cho 0.5%/0.3% ≈ 3–5×ATR trên EURUSD H1 → vô hiệu hoá lớp lọc retest. Mode `"percent"` giữ trong config |
| D6 | **Khớp ở open nến kế tiếp** | Quyết định ở close `[-1]` → khớp ở open `[+1]`. §6.1 xác nhận bằng close rồi entry = open cùng nến là look-ahead. Lag ON/OFF chung một quy ước khớp |
| D7 | **Entry sai phía SL → huỷ lệnh** | BUY: `entry <= sl` → CANCELLED; SELL: `entry >= sl` → CANCELLED. Ghi log, không bịa luật mới |
| D8 | **BREAKEVEN tính là LOSS trong các bộ đếm** | Tăng `daily_loss_count` + `consecutive_losses`. Cột `trade.result` vẫn lưu đủ 3 giá trị (xem "Phân loại kết quả") |
| D9 | **Phiên theo tz gốc, tự DST** | Forex+Crypto: London 08:00–17:00 Europe/London + NY 08:00–17:00 America/New_York (crypto KHÔNG 24/7 — sai lệch khỏi §7). Stock VN: 9:00–11:30 + 13:00–14:30 Asia/Ho_Chi_Minh |
| D10 | **Stock VN: 2 lệnh đồng thời, KHÔNG hạn mức thua/ngày** | Stock đánh D1/W1 ⇒ "3 lệnh thua/ngày" không kích được. Forex/Crypto giữ 3/3 (§6.7) |
| D11 | **4 SYMBOL_TYPE** | `FOREX / CRYPTO / STOCK_VN_CASH / STOCK_VN_DERIV`. CASH: `ALLOW_SHORT=false`, T+2.5, lô 100. DERIV: VN30F1M, short OK, có đáo hạn. Chi tiết Phase 2 |

## Quy ước kỹ thuật (C1–C12)

- **C1 — Index kiểu pandas:** `[-1]` = nến đã đóng gần nhất. Bỏ quy ước `close[0]` của §6.1 (convention MQL). Feed không bao giờ trả nến đang hình thành.
- **C2 — Nhân quả:** quyết định ở close `[-1]`, khớp ở open `[+1]`. Lag ON → nến tín hiệu `[-2]`, xác nhận `[-1]`. Lag OFF → tín hiệu `[-1]`.
- **C3 — Ngày giao dịch (Forex/Crypto): rollover 17:00 America/New_York.** 00:00 ICT rơi giữa phiên NY → reset đếm giữa phiên = nhân đôi hạn mức. Stock VN không dùng khái niệm này (D10).
- **C4 — `daily_loss_count` theo ngày giao dịch lúc ĐÓNG lệnh.**
- **C5 — Time Stop = đồng hồ thật** (`bar.close_time − entry_bar_ts ≥ 8h`), không đếm nến. Chỉ khi chưa chạm TP1 (`TIME_STOP_AFTER_TP1=false`). Lưu ý: time stop được xét tại `bar.close_time` bên trong `process_bar` khi clock hệ thống còn ở đầu bar — đúng nhân quả vì phép so chỉ dùng timestamp của bar, không dùng `clock.now`. Đừng "sửa" lại.
- **C6 — `RETEST_MAX_BARS = 5`** (§4 không nói đợi bao lâu).
- **C7 — Risk % từ config:** `MAX_RISK_PER_TRADE × risk_multiplier`. Bỏ `1.0` hardcode của §8.
- **C8 — Làm mượt:** ATR/ADX/RSI dùng **Wilder** (`alpha=1/period`, seed = SMA). EMA34/89 dùng **EMA chuẩn** (`alpha=2/(period+1)`, seed = SMA). Warmup = NaN, không phải 0.
- **C9 — Z-score: stdev mẫu (ddof=1)**, cửa sổ 100 **bao gồm** ATR hiện tại (§6.4 `range(-100,0)` chứa `atr[-1]`).
- **C10 — Mọi timestamp tz-aware UTC.** `datetime.now()` bị cấm trong engine — thời gian chỉ từ `Clock` inject. Test grep canh.
- **C11 — Nến khoá theo giờ MỞ; chỉ thấy khi `open_ts + tf_duration <= clock.now`.** Chống bẫy MTF: nến 4H đang hình thành chứa chính giờ hiện tại → EMA htf biết trước tương lai. `bars()` lọc trước `.tail(n)`. `test_no_lookahead.py` canh — không thương lượng.
- **C12 — NaN warmup:** filter nào đọc indicator NaN → `passed=None`, `stage="warmup"`; decision tổng = `reason="wait", stage="warmup"`. Không bao giờ so sánh NaN (NaN > 30 âm thầm ra False).

## Mapping 14 bộ lọc spec → 16 filter triển khai

§2 spec liệt kê 14. Triển khai có **16** vì: (a) `wick` — lớp 4 của Advanced Mode §4, tách thành filter riêng khi bỏ ADVANCED_FILTER_MODE (D3/D4); (b) `news` — §8 bước 3 gộp vào session, tách riêng để toggle độc lập.

| kind | Filters | Vai trò |
|---|---|---|
| REGIME | trend, adx, er | Chọn chế độ / chiến lược |
| INPUT | atr_ref *(locked — không tắt được, mọi SL phụ thuộc)* | Cấp ATR14/ATR5 |
| GATE | session, news, mtf, dxy, confirmation_lag, range_width, volume *(off cho FOREX)*, wick, account_risk | Chặn lệnh |
| MODIFIER | atr_zscore *(gate + `sl_scale`)*, equity_curve *(`risk_multiplier`)* | Điều chỉnh |
| EXIT | time_stop | Đóng lệnh |

Filter disabled → `enabled=False, evaluated=False, passed=None`, **không bao giờ chặn**.
Cả ADX lẫn ER disabled → điều kiện regime mặc định đúng → nhánh BREAKOUT thắng (theo thứ tự if/elif của §8 bước 6).

## Công thức SL/TP — đủ hai phía (mirror của §6.8)

| | BUY | SELL |
|---|---|---|
| Breakout SL | `range_low − 0.5×ATR14×sl_scale` | `range_high + 0.5×ATR14×sl_scale` |
| Breakout TP | `entry + 1.5×\|entry−sl\|` (TP1), `+3.0×` (TP2) | `entry − 1.5×\|entry−sl\|`, `−3.0×` |
| MR SL | `ema34_low[-1] − 1.0×ATR5[-1]` | `ema34_high[-1] + 1.0×ATR5[-1]` |
| MR TP | `ema34_close[-1]` (tuyệt đối, chốt lúc quyết định) | như BUY |
| Guard D7 | huỷ nếu `entry ≤ sl` | huỷ nếu `entry ≥ sl` |

`sl_scale` (atr_zscore) **không** áp cho MR (§6.8). MR không dời BE; Breakout dời BE khi chạm TP1.

## Sai lệch có chủ đích khỏi V1.2

1. Bỏ `ADVANCED_FILTER_MODE` (D3).
2. Bỏ bảng tham số §7 (D2).
3. Retest theo ATR (D5).
4. Entry ở open nến kế (D6).
5. Guard MR entry-sai-phía-SL (D7).
6. BREAKEVEN → LOSS cho bộ đếm (D8).
7. **TP/lot chốt lúc KHỚP** — hệ quả D6: `entry` chưa biết lúc quyết định. `place_order` lưu luật (`TPRules`) chứ không lưu số; SL chốt từ lúc quyết định. Risk thực tế đúng bằng `MAX_RISK_PER_TRADE × risk_multiplier`.
8. **Filter 4 (atr_ref) locked** — là input của mọi SL, không phải bộ lọc. UI render disabled + tooltip.
9. Crypto chạy phiên London & NY, không 24/7 (D9).
10. `SYMBOL_TYPE` 4 giá trị (D11).
11. Stock VN: 2 lệnh, tắt hạn mức/ngày (D10).
12. `ALLOW_SHORT` — khái niệm mới, bắt buộc cho STOCK_VN_CASH.
13. **`ONE_TRADE_PER_SYMBOL=true` chặn lệnh** → emit `reason="max_concurrent_trades_reached"`, `stage="one_trade_per_symbol"` — giữ từ vựng §8 khả tri trên 1 symbol.
14. **Xác nhận lag dùng ngữ nghĩa §6.1** (`close_confirm > close_signal` cho BUY), không phải "nến xanh" (`close > open`) của §5 — hai định nghĩa mâu thuẫn trong spec, chọn §6.1 vì nó là mục "chi tiết công thức".

## Phân loại kết quả (F2)

Tại thời điểm đóng hẳn lệnh (tổng hợp mọi phần):
`pnl > +eps → WIN`; `|pnl| ≤ eps → BREAKEVEN`; `pnl < −eps → LOSS` (eps = 1e-9 × equity).
Cột `trade.result` lưu đủ 3 giá trị cho UI. D8 chỉ sống trong bộ đếm:
`daily_loss_count = COUNT(result IN ('LOSS','BREAKEVEN'))`, streak coi BREAKEVEN như LOSS.

## Bộ đếm là DERIVED

`daily_loss_count` / streaks tính từ bảng `trade`; `account_state` chỉ là cache, có invariant test
cache == derived sau mỗi lệnh đóng. Lệch → derived thắng. Bug mutate-and-drift của
`reset_daily_counter_if_new_day()` (§6.7) không thể xảy ra về mặt cấu trúc.

## Dẫn giải fixture tính tay

Ghi tại `tests/fixtures/indicators/*.json` — mỗi file có trường `derivation` giải thích từng bước số học.
Chu kỳ ngắn (3, 5) để kiểm tay được; chu kỳ dài spot-check + assert NaN warmup.
Không cross-check ta-lib/pandas-ta: công thức §6 + C8 là chân lý.

## Gap còn lại — default đã chọn (config chỉnh được)

| Gap | Default |
|---|---|
| Phiên | tz gốc, tự DST (D9) |
| `MAX_CONCURRENT_TRADES` Phase 1 | `ONE_TRADE_PER_SYMBOL=true` ⇒ tối đa 1 lệnh (sai lệch 13) |
| Chạm `DAILY_MAX_LOSSES` | Chỉ chặn lệnh mới; lệnh mở vẫn quản tới SL/TP/time-stop |
| §6.5 HTF chỉ dùng `EMA34_Close vs EMA89_Close` | Đúng nguyên văn (gate HTF lỏng hơn primary — có vẻ cố ý) |
| `STARTING_EQUITY`, instrument | 10 000 USD; EURUSD `contract_size 100000, pip 0.0001, pip_value_per_lot 10.0, spread_pips 0.0, min_lot 0.01`. Spread 0 để test tính tay; §10 bắt backtest có phí → bật khi chạy thật |
| News | `NEWS_BLACKLIST=[]`, filter off; nhận list khoảng UTC nhập tay |
