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
**Foot-gun UI (user chốt 2026-07-18)**: vì tắt cả hai = breakout-mọi-lúc (fail-open), trang Config phải hiện dialog xác nhận khi user tắt filter thứ hai trong cặp {adx, er} — chỉ tắt sau khi confirm (việc làm: plan 09 §4).

## Công thức SL/TP — đủ hai phía (mirror của §6.8)

| | BUY | SELL |
|---|---|---|
| Breakout SL | `min(retest_low, range_high) − 0.5×ATR14×sl_scale` | `max(retest_high, range_low) + 0.5×ATR14×sl_scale` *(sửa 2026-07-19, xem mục cuối — trước đây neo `range_low`/`range_high` phía xa)* |
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
15. **`lot_below_min`** — không đủ vốn cho 1 lô nguyên → `reason="wait"`, `stage="lot_below_min"` (plan 05).
16. **Bỏ làm tròn tick HOSE** — dùng giá CSV thô, không làm tròn về bước giá 50/100/500đ (plan 05).
17. **Bỏ trần/sàn ±7% HOSE** — không mô phỏng giới hạn biên độ khi giá gap (plan 05).
18. **Đáo hạn VN30F chỉ theo lịch** — thứ Năm tuần 3, không xử lý ngày nghỉ lễ (plan 05).
19. **Không mô phỏng margin VN30F** — risk theo `MAX_RISK_PER_TRADE` như mọi instrument khác (plan 05).
20. **Tài khoản VND tách biệt cho stock VN** — cấm trộn symbol VN với FOREX/CRYPTO trong một run (plan 05).
21. **T+2.5 chặn thoát lệnh** — SL/TP không kích hoạt trước khi hàng về, chỉ ghi `exit_suppressed_settlement` (plan 05).

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
| News | **Vượt qua bởi plan 06** (mục "Plan 06 — Dữ liệu cho filter `news`" cuối file): dữ liệu thật (`news_event` import từ CSV chuẩn hoá), không còn `blacklist_utc` nhập tay |

## Quyết định phát sinh trong Phase 2/3 (chưa có ở trên, ghi bổ sung)

- **[Plan 01] Lot size chốt lúc khớp, dùng entry thật** — nợ kỹ thuật #1 ở trên đã trả:
  `risk_manager.calculate_lot` chuyển từ `main_loop.decide` vào `OrderEngine.process_bar`
  nhánh fill `PENDING`, dùng `entry` vừa fill (`risk_distance = |entry - sl|` thật, không còn
  ước lượng bằng `close[-1]`). `OpenTrade` mang `risk_pct_effective` (= `max_risk_per_trade_pct
  x risk_multiplier`, chốt tại quyết định vì hai giá trị này không đổi giữa bar quyết định và
  bar khớp) thay vì `lot_size` — `lot_size` giờ mặc định `0.0` và chỉ được set lúc khớp. Nếu
  lot tính ra ở entry thật làm tròn về 0 (hiếm, nhưng có thể khác so với ước lượng), lệnh
  PENDING bị CANCELLED tại khớp với detail `"lot size rounds to zero at fill"` — decision
  `reason` cho bar đó vẫn là `done` (giữ nguyên vựng §8; “no_signal”/stage=`risk_manager` tại
  quyết định không còn xảy ra qua đường này). Trade row PENDING insert với `lot_size=NULL`
  (ít phá schema nhất — decision row chưa từng lưu lot); `UPDATE` khi `FILLED` set `lot_size`
  thật. Test: `test_lot_sized_off_real_fill_entry_not_estimate` (risk thực tế đúng
  `equity x risk_pct_effective/100` trong sai số 1 lot-step, dùng bar gap-open để entry ≠
  close[-1]) và `test_lot_rounds_to_zero_cancels_pending_order_at_fill`
  (`tests/unit/test_order_engine.py`). Golden hash đổi (xem cuối mục), đã re-pin.
- **[Plan 01] `INTRABAR_PRIORITY="path"` dùng sub-bar path thật khi có** — nợ kỹ thuật #2 đã
  trả: `synthetic.py` giờ lưu `sub_path` (16 điểm giá, `open→…→close`) trên `df15` mỗi candle;
  cột này bị resample bỏ qua tự nhiên khi lên 1H/4H/1D/1W (`resample_fixed`'s `.agg()` chỉ động
  tới các cột OHLCV được đặt tên) nên **chỉ có mặt trên khung `15m`** — đúng giới hạn plan
  cho phép ("chỉ hỗ trợ khi TIMEFRAME=15m"). `Bar` có field `sub_path: tuple[float,...] | None`;
  `Feed.bar_at` đọc cột này nếu tồn tại. `order_engine._bar_exit` nhận thêm `sub_path`: khi
  `priority="path"` và có path, duyệt tuần tự từng đoạn (16 điểm → 15 đoạn), mốc SL/TP nào
  nằm trong `[min,max]` của đoạn trước thắng; nếu path không có (CSV thật hoặc timeframe ≠ 15m)
  thì fallback về xấp xỉ cũ (mốc gần `open` hơn thắng). Giới hạn còn lại (chấp nhận được, ghi
  ở đây thay vì làm thêm): lần duyệt thứ hai trong cùng bar (sau khi TP1 khớp, kiểm tra phần
  còn lại so với breakeven/TP2) dùng lại **toàn bộ** `sub_path` của bar thay vì cắt đúng đoạn
  còn lại sau điểm chạm TP1 — cần `_walk_path_first_touch` trả thêm chỉ số đoạn để cắt chính
  xác, không đáng độ phức tạp thêm ở plan này. Test: `test_path_priority_uses_real_sub_path_when_available`,
  `test_synthetic_sub_path.py` (`tests/unit/`). Golden hash đổi (xem dưới), đã re-pin.

**Golden hash re-pin (bất biến #1, sau khi trả 2 nợ kỹ thuật trên):** `python -m bot.cli replay
--seed 42 --bars 2000` chạy 2 lần liên tiếp cho cùng
`decision_stream_hash=460ea65e1e977c12b7ef93189e17c35fa1a72016fb893f037d17f1fc57d3ab8f`,
final equity `9986.424648678441` — ổn định, không có giá trị hash cũ nào được ghim cứng trong
test trước đó (`tests/integration/test_replay_golden.py` chỉ so sánh hai lần chạy với nhau,
không so với hằng số), nên không có gì cần sửa trong test suite ngoài các test đơn vị đã liệt
kê ở trên.

- **[Plan 01] A/B filter harness (`python -m bot.cli ab --seed 42 --bars 5000`)** — với từng
  filter trong registry (trừ `atr_ref` khoá), chạy baseline vs. biến thể đảo `enabled`, so
  `decision_stream_hash` + số lệnh. Ở `seed=42, bars=5000`: `confirmation_lag`, `session`,
  `adx_filter`, `er_filter`, `trend` đều đổi hash đúng như kỳ vọng của plan.
  **`mtf` KHÔNG đổi hash** dù có mặt trong danh sách "phải đổi" của plan gốc — kiểm chứng đây
  không phải lỗi: breakout signal vốn trend-following nên hướng của nó gần như luôn đồng
  thuận với HTF trend (EMA34 vs EMA89 trên timeframe cao hơn), xung đột mtf hiếm xảy ra trên
  dữ liệu synthetic — cùng loại "hiếm" đã ghi nhận cho MR (3 điều kiện AND). Cơ chế block của
  `mtf` vẫn được chứng minh đúng bằng test dựng tay (`test_mtf_blocks_buy_when_htf_bear`,
  `tests/unit/test_filters.py`). Đã chuyển `mtf` vào danh sách "có thể trơ" của harness
  (`_AB_MAY_BE_INERT`, `bot/cli.py`) — harness in cảnh báo thay vì fail khi các filter trong
  danh sách này không đổi hash. Danh sách đầy đủ các filter "có thể trơ": `news` (off mặc
  định), `dxy`, `volume` (off cho FOREX), `atr_zscore`, `equity_curve`, `range_width`, `wick`,
  `account_risk`, `time_stop`, `mtf`. Test tự động: `tests/integration/test_ab_filters.py`
  (`@pytest.mark.slow`).
- **Breakout-retest signal được tôn trọng bất kể nhãn regime của đúng bar khớp retest** — máy trạng thái retest (`strategies/breakout_retest.py`) chạy mỗi bar không điều kiện (yêu cầu của plan), nhưng khi retest hoàn tất và phát tín hiệu, `main_loop.decide` LUÔN dùng tín hiệu đó làm `signal` chính, không kiểm tra lại xem bar khớp retest có đang ở "regime trend" hay không (điều kiện trend chỉ áp dụng lúc breakout ban đầu được ghi nhận). *Ghi chú 2026-07-19: mô tả trên là Ý ĐỊNH, nhưng code cũ chưa làm đúng — điều kiện regime bị xét ở bar retest, còn việc ARM breakout lại KHÔNG xét regime (lỗ hổng: breakout arm & khớp cả trong regime range). Đã sửa đúng ý định này, xem mục "Sửa phễu tín hiệu" cuối file.*
- **MEAN_REVERSION hiếm khi khớp đủ 3 điều kiện đồng thời (ADX<25 AND ER<0.3 AND RSI quá mua/bán)** — đã kiểm chứng bằng dữ liệu synthetic: với tham số mặc định, tổ hợp cả ba điều kiện xảy ra ~1 lần / 20 000 bar H1. Đây không phải lỗi — về bản chất RSI cực trị thường đi kèm biến động có hướng (ADX tăng), trong khi MR yêu cầu đúng lúc thị trường "range". `python -m bot.cli replay --seed 42 --bars 5000` vì vậy thường chỉ sinh lệnh BREAKOUT; test suite (`test_main_loop.py`) verify từng nhánh MR bằng context dựng tay thay vì phụ thuộc random walk.
- **`dxy_change_1h_pct`** tính bằng `(close[-1] - close[-1-lookback_hours]) / close[-1-lookback_hours] * 100` trên khung 1H của chuỗi DXY resample — công thức % thay đổi chuẩn, `lookback_hours` lấy từ `filters.dxy.lookback_hours` (mặc định 1).
- ~~`account_state.open_trades` trong Phase 2/3 chỉ phản ánh 0 hoặc 1...~~ **Vượt qua bởi
  plan 04** (mục "Plan 04 — Đa symbol" cuối file): `open_trades_count` giờ portfolio-wide thật,
  `Runner` nhận `dict[str, SymbolContext]` (mỗi symbol một `OpenTrade | None`), không còn giới
  hạn 0/1 hay `OpenTrade | None` đơn lẻ.

## Dữ liệu thật & chi phí (Plan 02)

- **Chính sách gap**: import CSV KHÔNG fill bar thiếu — engine vốn xử lý chuỗi bar đóng tuần
  tự nên gap (cuối tuần forex, ngày nghỉ lễ VN...) là hợp lệ. `count_grid_gaps` chỉ đếm số
  slot thiếu trên lưới (anchor tại bar đầu tiên cho 15m/1H/4H; số ngày lịch thiếu cho 1D) và
  ghi vào `dataset.gap_count` — thông tin hiển thị, không chặn import/run. Việc lệch lưới
  (timestamp không phải bội số của tf, hoặc 1D không cùng giờ-phút-giây trong ngày) mới bị từ
  chối (`FeedError`), vì đó là lỗi dữ liệu chứ không phải gap. *Sửa 2026-07-20 (review):
  (a) `load_csv` từng `sort_index()` TRƯỚC khi validate — check "index tăng nghiêm ngặt"
  không bao giờ bắt được file lộn thứ tự; giờ bỏ sort, file out-of-order bị `FeedError` kèm
  timestamp dòng vi phạm. (b) Idempotency của `import_csv_dataset` đổi khoá từ `file_sha256`
  đơn lẻ sang bộ ba `(file_sha256, symbol, native_tf)` (đúng bộ ba tạo dataset id) — cùng
  file import dưới symbol/tf KHÁC giờ đăng ký dataset mới thay vì âm thầm trả metadata của
  dataset cũ. (c) `create_run(dataset_id=…)` với config >1 symbol giờ raise `ConfigError`
  thay vì âm thầm bỏ qua `dataset_id` và sinh synthetic.*
- **Căn chỉnh thời gian DXY**: theo đúng C11 — giá trị DXY nhìn thấy tại clock `t` luôn là bar
  DXY đã đóng gần nhất tính tới `t` (`Feed.bars()` filter trước `.tail(n)` như giá chính), KHÔNG
  bao giờ forward-fill từ tương lai. Nếu chuỗi DXY thiếu bar tại thời điểm đánh giá, filter
  `dxy` trả `passed=None, stage="no_data"` (đã có sẵn từ Phase 2, không đổi) thay vì chặn lệnh.
  `filters.dxy.dataset_id` (mới) trỏ tới một dataset `kind='csv', symbol='DXY'` đã import riêng;
  để trống thì dùng DXY synthetic bundled như trước (không đổi hành vi mặc định).
- **Mô hình slippage bảo thủ (§10)**: `execution.costs.slippage_pips` luôn làm xấu đi giá vào
  lệnh (spread + slippage cộng bất lợi vào cả BUY lẫn SELL) và giá thoát SL (kể cả SL đã dời
  về breakeven sau TP1, và cả trường hợp gap-through-SL fill tại giá mở bar) — không bao giờ
  cải thiện. Giá TP giữ nguyên, không cộng/trừ gì — mô hình cố ý bảo thủ (không lạc quan hoá
  kết quả backtest). `commission_per_lot` trừ một lần vào `pnl_amount` lúc đóng lệnh hoàn toàn
  (theo tổng `lot_size`, không theo phần TP1 lẻ), KHÔNG đụng vào `pnl_r` — R-multiple giữ là
  một đại lượng thuần khoảng-cách-giá để các filter dựa trên streak/equity-curve không bị ảnh
  hưởng bởi cấu hình chi phí. Tất cả cost mặc định = 0 nên `test_replay_golden` không đổi hash;
  `test_replay_golden_with_costs` pin một hash riêng khi cost > 0.

## Sửa phễu tín hiệu & cấu trúc R (2026-07-19)

Backtest thực tế cho ra rất ít lệnh và thua ròng. Rà soát toàn bộ chuỗi
strategy → filter → decision tìm ra 2 bug ghép nối + một cụm tham số tự triệt tiêu nhau.
Các thay đổi (đổi hành vi mặc định — golden stream đổi là CHỦ ĐÍCH):

1. **Regime gate chuyển về thời điểm ARM (bar breakout), không phải bar retest**
   (`main_loop.decide` → `breakout_retest.evaluate(arm_buy, arm_sell, min_range_atr_mult)`).
   Trước đây: (a) tín hiệu retest bị `wait` nếu regime "nhấp nháy" đúng bar retest — mâu
   thuẫn với diễn giải đã ghi ở mục Phase 2/3; (b) **bug thật**: khi regime là RANGE
   (candidate=MEAN_REVERSION), tín hiệu breakout vẫn lọt qua `resolve_decision` và ĐẶT LỆNH —
   phần lớn lệnh khớp thực tế là false-breakout trong vùng chop. Giờ: breakout mới chỉ được
   ARM khi candidate=BREAKOUT **và** hướng khớp trend mode (BULL→BUY, BEAR→SELL); một khi đã
   arm, retest sống sót qua nhấp nháy regime (đúng tinh thần plan). `resolve_decision` chỉ
   `wait/regime` khi **không** có tín hiệu.
2. **`range_width` chuyển thành điều kiện ARM** — trước đây nó chỉ được xét khi `signal is
   None` trong `resolve_decision`, tức KHÔNG BAO GIỜ chặn được lệnh nào (no-op). Giờ độ rộng
   range tiền-breakout (`range_high − range_low > atr_mult × ATR14`) được kiểm ngay tại bar
   breakout trong state machine.
3. **Retest bị filter hạ nguồn chặn KHÔNG đốt state** — trước đây `evaluate` reset về
   `initial()` ngay khi phát tín hiệu, kể cả khi wick/mtf/session/account_risk chặn lệnh.
   Giờ `main_loop` giữ `AWAITING_RETEST` (tăng `bars_waited`) trong ngân sách C6 còn lại.
4. **SL breakout neo theo bar retest, chặn trên tại level đã phá** (bảng mirror ở trên).
   Công thức cũ `range_low − 0.5×ATR` làm 1R ≈ cả bề rộng range (≥ 2×ATR do range_width
   yêu cầu width > 1.5×ATR) ⇒ TP1 = 1.5R ≈ 3×ATR — ngoài tầm với của time stop ⇒ phân phối
   kết quả chỉ còn SL −1R và TIME_STOP nhiễu ⇒ thua ròng cấu trúc.
5. **Time stop theo bar** (`filters.time_stop.bars = 16`, nhân `tf_duration`; `hours` giữ làm
   fallback khi `bars: null`) — C5 "8h đồng hồ thật" thù địch với timeframe: 4H chết sau 2
   bar, 1D chết ngay bar đầu. Ngữ nghĩa so sánh wall-clock trong `is_expired` GIỮ NGUYÊN
   (vẫn C5), chỉ ngân sách giờ được suy từ bar × timeframe tại `Runner.__init__`.
6. **`confirmation_lag` không áp cho BREAKOUT** — retest tự thân đã có xác nhận
   (`close` vượt lại level); check `close[-1] > close[-2]` (sai lệch #14) loại đúng hình
   mẫu pullback-rồi-từ-chối kinh điển (close bar trước cao hơn là tất yếu khi đang pullback
   BUY). Giữ nguyên cho MEAN_REVERSION.
7. **Nới tham số tự-triệt-tiêu** (default.yaml + models.py đồng bộ): ADX trend 30→25
   (ADX trễ — sau range 20 bar hầu như không kịp >30 trong 5 bar retest), range 25→23;
   ER trend 0.6→0.35 (0.6/10-bar ≈ đường thẳng tuyệt đối, AND với ADX-trend gần như không
   bao giờ đồng thời), range giữ 0.30; wick 0.5→0.33 (D4 revised); `sl_scale_mid` 1.5→1.2
   (trước bằng đúng `sl_scale_high` — dải mid vô nghĩa).

Kiểm chứng: unit + integration suite pass (golden test chỉ so determinism giữa 2 lần chạy,
không pin hằng số nên không cần re-pin); xem thêm histogram lý do trong bảng `decision` để
so trước/sau trên dữ liệu thật.

## Plan 04 — Đa symbol: portfolio thật (2026-07-19)

Xoá ghi chú "0/1" cũ (mục Phase 2/3 phía trên, dòng về `account_state.open_trades`):
`open_trades_count` giờ là **portfolio-wide thật** (tổng lệnh mở/pending qua mọi symbol),
`Runner`/`OrderEngine` nhận `dict[str, SymbolContext]` (mỗi symbol một `OpenTrade | None`
trong `SymbolContext.trade`) thay vì `OpenTrade | None` đơn lẻ. Order xử lý symbol trong
cùng một mốc clock là **alphabet** (deterministic).

1. **`Runner.step()` đổi shape trả về**: `list[StepSummary]` (một phần tử/symbol xử lý ở
   tick đó) thay vì `StepSummary | None`. Một "tick" là mốc bar-close SỚM NHẤT trong số mọi
   symbol (mỗi symbol timeframe riêng); mọi symbol đóng bar đúng tick đó được xử lý theo thứ
   tự alphabet — đây là cơ chế quyết định ai giành slot cuối khi 2 symbol cùng tín hiệu `done`
   trong cùng tick (`MAX_CONCURRENT_TRADES`). Test: `tests/unit/test_multi_symbol_clock.py`,
   `tests/unit/test_account_risk_portfolio.py`.
2. **Dataset seed derivation — chỉ đổi khi có >1 symbol** — `bot.data.dataset.
   named_child_seed(base_seed, symbol)` (SeedSequence + spawn_key = hash tên symbol) áp dụng
   khi `len(enabled symbols) > 1`, để thêm symbol không đổi stream của symbol cũ. Config
   1-symbol (auto-migrated, trường hợp phổ biến nhất) dùng **thẳng `base_seed`** — đạt đúng
   mục tiêu lý tưởng của plan ("hành vi phải giống hệt bản trước"): dataset, decision stream
   VÀ equity của mọi golden test 1-symbol giữ nguyên bit-for-bit so với trước plan 04.
   Phát hiện khi review: ban đầu áp `named_child_seed` cho MỌI config kể cả 1-symbol — dataset
   đổi khiến `test_costs_strictly_hurt_equity_vs_zero_cost_golden_run` fail (một shift giá vào
   lệnh nhỏ do spread/slippage đổi thời điểm chạm SL/TP intrabar, khiến trade chạy xa hơn thay
   vì dừng breakeven cùng bar — hiệu ứng cánh bướm vốn có của backtest theo bar, không phải bug
   logic) — đã sửa bằng quy tắc trên thay vì nới lỏng assertion của test.
3. **DXY dùng chung cho cả portfolio** — lấy từ symbol FOREX đầu tiên (alphabet) trong danh
   sách enabled, tái dùng bundle `dxy` được sinh cùng lúc với giá symbol đó (không sinh dataset
   DXY riêng) — đơn giản hoá so với "mỗi symbol tự tương quan DXY", chấp nhận được vì filter
   `dxy` chỉ đọc %-thay-đổi, không phân biệt tương quan với symbol nào.
4. **Giới hạn phát hiện khi build multi-symbol demo (quan trọng, không phải phần plan yêu
   cầu nhưng bắt buộc phải xử lý để tránh kết quả sai)**: `OrderEngine._pnl_amount` tính
   `price_move × lot × contract_size` và coi thẳng kết quả là tiền tài khoản (USD) — đúng khi
   **quote currency == account currency** (EURUSD, GBPUSD, XAUUSD đều quote bằng USD). Với
   **USDJPY** (quote = JPY), công thức này sai hoàn toàn nếu không quy đổi JPY→USD theo tỷ giá
   — gây lãi/lỗ ảo gấp hàng trăm lần risk dự kiến (đã bắt được khi review: một lệnh 1% risk
   cho ra pnl thật -$546 trên equity 500). Đây là **giới hạn kiến trúc có trước plan 04**
   (engine vốn build cho 1 symbol EURUSD), không phải bug của plan 04, và **không sửa ở đây**
   — phạm vi multi-currency P&L conversion là việc của plan 10 (forex đa venue). Xử lý: `config/
   instruments.yaml` vẫn giữ `USDJPY` (pip=0.01) làm entry hợp lệ CHO RIÊNG mục đích test
   `risk_manager.calculate_lot` cách ly (pip≠EURUSD sizing, `tests/unit/test_risk_manager.py`)
   — không dùng USDJPY trong bất kỳ multi-symbol integration/golden test hay portfolio mẫu
   nào; các test đó dùng EURUSD/GBPUSD/XAUUSD (đều quote-USD, P&L đúng với engine hiện tại).
   **Bổ sung 2026-07-20 (review plans 01–06): bất biến sizing↔P&L** — vì sizing dùng
   `pip_value_per_lot` còn P&L dùng `contract_size`, mọi entry trong `instruments.yaml`
   PHẢI thoả `pip_value_per_lot == pip × contract_size` (tính bằng USD) chừng nào engine
   chưa có quy đổi quote-currency. Review bắt được XAUUSD khai `pip_value_per_lot: 1.0`
   trong khi `pip(0.1) × contract_size(100) = 10.0` → lot bị oversize đúng 10× (lệnh
   "risk 0.5%" thực tế thua ~5% equity tại SL). Đã sửa thành `10.0`; golden multi-symbol
   không cần re-pin hằng số (test chỉ so determinism giữa 2 lần chạy) nhưng stream/equity
   của portfolio chứa XAUUSD đổi là CHỦ ĐÍCH.
5. **`account_risk` filter thêm nhánh `total_risk_cap`** — khi `risk.max_total_open_risk_pct`
   được set (mặc định `None` = tắt, không đổi hành vi/hash), tổng `risk_pct_effective` của
   mọi lệnh mở/pending vượt ngưỡng → `reason=max_concurrent_trades_reached`,
   `stage=total_risk_cap` (từ vựng §8 giữ nguyên, chỉ thêm stage — đúng deviation #13).
6. **`decision.symbol`, `run.symbols_json`, `run_symbol_dataset`** thêm ở migration
   `003_multi_symbol.sql`. `run.symbol`/`run.dataset_id` giữ nguyên vai trò hiển thị
   (comma-joined / symbol đầu tiên theo alphabet) — không còn là nguồn chân lý, chỉ để không
   phá các chỗ đang đọc 2 cột này.
7. **Chart nến (`/api/runs/{id}/bars`) vẫn chỉ hiển thị 1 symbol** (symbol đầu của run, qua
   `run.dataset_id`) — không mở rộng dropdown-chọn-symbol cho chart trong plan này (Decisions/
   Trades đã có filter theo symbol; Dashboard có bảng vị thế `open_trades_by_symbol` đủ mọi
   symbol). Giới hạn phạm vi có chủ đích, không phải thiếu sót.

Kiểm chứng: `python -m bot.cli replay --seed 42 --bars 600` (1-symbol, auto-migrated) chạy 2
lần cho `decision_stream_hash` ổn định; portfolio 3-symbol (EURUSD/GBPUSD/XAUUSD) qua API tạo
ra cả 2 stage `max_concurrent_trades` và `one_trade_per_symbol` trong decision histogram
(xem `tests/unit/test_account_risk_portfolio.py`). *Sửa 2026-07-20: nhánh chặn theo tổng
portfolio ban đầu emit `stage="account_risk"` — đã đổi thành `stage="max_concurrent_trades"`
đúng từ vựng plan 04 (nhánh daily-loss-limit vẫn giữ `stage="account_risk"`, plan không đặt
tên riêng cho nó).*

## Plan 06 — Dữ liệu cho filter `news` (blackout windows) (2026-07-20)

Thay `filters.news.blacklist_utc` (list khoảng UTC nhập tay) bằng dữ liệu sự kiện thật, import
từ file lịch kinh tế đã export (user tự tải, KHÔNG scrape/gọi API — đúng ràng buộc plan).

1. **Format chuẩn nội bộ**: bảng `news_event(id, ts_utc, currency, impact, title,
   source_file_sha256, created_at_utc)`, migration `004_news_events.sql`. Dedupe **tại insert**
   bằng unique index `(ts_utc, currency, title)` — import lại cùng file/khoảng thời gian là
   no-op (`INSERT OR IGNORE`, đếm `inserted_count`/`duplicate_count`). Bảng append-only, không
   bao giờ UPDATE/DELETE một dòng đã insert.
2. **`scripts/convert_news.py`**: đổi file export ForexFactory (cột `Date,Time,Currency,
   Impact,Event`, giờ theo `--tz` — mặc định `America/New_York`, đúng default của
   ForexFactory) sang CSV chuẩn `ts_utc,currency,impact,title` (ts ISO-8601 UTC). Bỏ dòng
   `Impact=Holiday` (không phải sự kiện có thể trade quanh). Cùng pattern với
   `scripts/convert_csv.py` (plan 02).
3. **Import**: `python -m bot.cli import-news --path <file chuẩn>` + `POST /api/news/import
   {path}` (`bot.data.news.import_news_csv`) — validate cột bắt buộc, `ts_utc` phải
   timezone-aware ISO-8601, `impact` phải thuộc `low|medium|high`.
4. **`filters.news`**: `enabled` (mặc định `false`, giữ golden hash không đổi), `min_impact`
   (`low|medium|high`, mặc định `high`), `window_before_min`/`window_after_min` (mặc định
   30/30 phút). **`currencies` KHÔNG nằm trong config filter** — lấy từ `InstrumentSpec.
   currencies` (field mới, `config/instruments.yaml` mỗi symbol khai một lần, ví dụ
   EURUSD → `[EUR, USD]`) đúng yêu cầu "không hardcode trong filter, đặt trong
   instrument/profile". Ngữ nghĩa chặn: tồn tại event `impact` ≥ `min_impact`, `currency`
   giao với `currencies` của symbol, và `now ∈ [event.ts − window_before_min,
   event.ts + window_after_min]` → `passed=False`, `blocking=True`.
5. **Reason/stage**: giữ đúng vựng §8 (`reason="wait"`, bất biến #4) — `stage` tách riêng
   thành `news_blackout` (trước đây gộp chung với `session` theo ghi chú Gap cũ; nay `news` đã
   luôn là filter/decision-log nhánh riêng, chỉ đổi TÊN stage từ `"news"` → `"news_blackout"`
   cho rõ nghĩa trên UI/API).
6. **Nạp vào `Context` — snapshot per-run (Determinism, bất biến #1)**: `Runner.__init__` đọc
   `run.news_snapshot_max_id` (cột mới, set bởi `repo.create_run` = `MAX(news_event.id)` tại
   thời điểm tạo run) rồi load TOÀN BỘ event có `id ≤ snapshot` một lần (`bot.data.news.
   load_news_events_index`) thành `NewsEventsIndex` (list sort theo `ts_utc`, tra cứu
   O(log n + k) bằng `bisect` — pure, không I/O, sống trong `bot.core.types` để `FilterContext`
   giữ được bất biến #6 "filter thuần, không I/O"; chỉ `bot.data.news` — nơi Runner gọi — mới
   chạm DB/file). Vì `news_event` append-only và mỗi run tự chốt `news_snapshot_max_id` lúc
   tạo, import file mới **không bao giờ đổi** decision stream của run đã tồn tại — chỉ run mới
   tạo SAU import mới thấy event đó. Test: `tests/integration/test_news_import.py`.
7. **UI**: `filters.news` render tự động qua `/api/config/schema` (bất biến #9, không sửa tay
   form) — nhưng phát hiện khi review: `FilterConfigPanel.tsx` trước đây KHÔNG render field
   kiểu `string`/`enum` (chỉ có nhánh `boolean`/`number`) vì trước plan 06 chưa filter nào có
   tham số dạng chuỗi — `min_impact` (Literal) sẽ bị silently drop khỏi form. Đã thêm nhánh
   `type === 'string'` (dropdown nếu có `enum`, text input nếu không) — sửa luôn gap này cho
   mọi filter tương lai, tiện thể làm lộ ra `filters.dxy.dataset_id` (string, có từ plan 02)
   cũng từng bị ẩn. Thêm card "Lịch tin tức" trên trang Config: form import theo đường dẫn +
   bảng read-only `GET /api/news?from=&to=` (không giới hạn theo snapshot của run nào — chỉ để
   xem trước, không ảnh hưởng determinism).

Golden hash không đổi (`filters.news.enabled=false` mặc định) — xác nhận bằng
`tests/integration/test_replay_golden*.py` chạy lại sau plan này, không cần re-pin.

## Plan 05 — Chứng khoán VN: STOCK_VN_CASH + STOCK_VN_DERIV (2026-07-22)

Hai symbol_type còn lại của D11 chạy đầy đủ trong backtest. **Mọi ❓ của plan đã được user
chốt trước khi code** (yêu cầu cuối plan 05) — các quyết định ghi ngay dưới đây.

### Quyết định user (2026-07-22)

| # | Điểm | Chốt |
|---|---|---|
| 1 | Mô hình T+2.5 | **Chặn thoát lệnh** tới phiên chiều ngày giao dịch thứ 2 sau entry; giá chạm SL/TP trong khoảng đó chỉ ghi `exit_suppressed_settlement` — backtest trung thực với rủi ro không cắt được |
| 2 | Khung VN30F | **Chỉ D1**, KHÔNG định nghĩa bar H4 trên phiên VN (không thêm `resample_origin`) |
| 3 | Tiền tệ | **Tài khoản VND riêng**; `starting_equity` đọc là VND khi mọi symbol là VN; **cấm trộn** VN với FOREX/CRYPTO trong một run |
| 4 | Không đủ 1 lô nguyên | `reason="wait"`, `stage="lot_below_min"` (sai lệch #15) |
| 5 | Chuỗi VN30F liên tục | **Script `scripts/stitch_vn30f.py`** ngoài engine, xuất chuỗi back-adjusted |
| 6 | Đơn giản hoá | Bỏ cả 4: tick HOSE, trần/sàn ±7%, lịch nghỉ lễ cho đáo hạn, margin VN30F (sai lệch #16–19) — **user ghi chú: gom thành một plan nâng cao cho phái sinh VN**, xem `plans/12-execution-realism.md` mục "12e" |

### Triển khai

1. **Ngày giao dịch VN = ngày lịch Asia/Ho_Chi_Minh (D10)** — `trading_day()` được viết lại
   theo **shift modulo**: `(24h − rollover) mod 24h`, cộng vào giờ địa phương rồi lấy `.date()`.
   Cách cũ (`if local.time() >= rollover: +1 ngày`) **hỏng ở mốc nửa đêm**: `>= 00:00` luôn
   đúng nên MỌI timestamp bị đẩy lên một ngày. Với 17:00 NY công thức mới cho kết quả **y hệt**
   cách cũ ở mọi mốc (kể cả đúng 17:00:00 và hai chiều DST) nên forex/crypto không đổi hành vi.
   `trading_day_start_local()` là mốc BẮT ĐẦU của ngày giao dịch (17:00 hôm trước / 00:00 hôm
   đó) — `resample_trading_day`/`resample_trading_week` neo bar theo hàm này thay vì hardcode
   "hôm trước". Test: `test_stock_vn.py::test_midnight_rollover_does_not_shift_every_bar_forward`.
2. **Bar D1 an toàn cho VN** — cả phiên (02:00–07:45 UTC) nằm gọn trong một ngày UTC *và* một
   ngày ICT, nên gom theo lưới nào cũng ra cùng bar; có test đối chiếu hai lưới
   (`test_vn_daily_bar_grid_is_identical_under_utc_and_ict_days`).
3. **Profile theo SYMBOL_TYPE** (`bot/config/profiles.py`, MỚI) — thứ tự ưu tiên:
   **config toàn cục < profile < `overrides` per-symbol**. Profile nằm giữa vì luật thị trường
   VN là thuộc tính của thị trường, không phải sở thích user: người đặt `timeframe: 15m` cho
   forex không được vô tình chạy HPG trên 15m. Profile VN đặt: `timeframe=1D`, rollover
   ICT/00:00, `account_risk.max_concurrent_trades=2`, `daily_loss_limit_enabled=false` (D10),
   `time_stop.enabled=false` (TF > H1), `dxy.enabled=false` (§6.6 là forex), `allow_short=false`
   cho CASH / `true` cho DERIV. **FOREX/CRYPTO có profile RỖNG** → hành vi và golden stream
   không đổi (có test canh: `test_forex_profile_is_empty_so_defaults_are_untouched`).
4. **Cấm trộn VND/USD** — validator trên `BotConfig` raise nếu danh sách symbol vừa có VN vừa
   có FOREX/CRYPTO. Lý do là giới hạn kiến trúc đã ghi ở plan 04: `OrderEngine._pnl_amount`
   không quy đổi tiền tệ (bug USDJPY), nên trộn sẽ cộng thẳng P&L VND vào equity USD. Khi
   portfolio toàn VN, validator cũng đặt rollover tài khoản về ICT/00:00 (Runner đọc rollover
   từ config gốc, không phải per-symbol). Validator ghi có điều kiện (`if != giá trị đích`) vì
   `validate_assignment=True` sẽ chạy lại validator sau mỗi phép gán → gán vô điều kiện là đệ quy.
5. **`instruments.yaml`** — HPG/FPT (lô 100 cp, `pip=1` VND, `pip_value_per_lot=100`) và
   VN30F1M (`contract_size=100_000` VND/điểm, `pip=0.1`, `pip_value_per_lot=10_000`). Cả ba giữ
   **bất biến sizing↔P&L** `pip_value_per_lot == pip × contract_size` (có test). **Lô nguyên
   không cần code mới**: `min_lot = lot_step = 1` là đủ — `calculate_lot` vốn đã floor theo
   `lot_step` và trả 0 khi dưới `min_lot`.
6. **`lot_below_min` (sai lệch #15)** — `main_loop` tính **lô tạm** tại thời điểm quyết định
   (entry ước lượng = `close[-1]`); nếu dưới 1 lô thì KHÔNG đặt lệnh, emit `wait/lot_below_min`.
   `FilterContext`/`SymbolContext` mang thêm `instrument` để làm việc này (không filter nào đọc,
   chỉ là dữ liệu thuần → bất biến #6 giữ nguyên). Backstop cũ ở `OrderEngine` (huỷ PENDING khi
   lô làm tròn về 0 tại giá khớp thật) **vẫn giữ** cho trường hợp entry thật đổi kết quả.
   *Đây là thay đổi hành vi cho MỌI symbol_type* (trước đây lệnh vẫn được đặt rồi bị huỷ lúc
   khớp): trên forex mặc định gần như không kích được (equity 500, min_lot 0.01), và golden test
   chỉ so determinism giữa 2 lần chạy chứ không ghim hằng số nên không cần re-pin.
7. **`ALLOW_SHORT` (sai lệch #12)** — chặn ở `main_loop` sau `resolve_decision`: tín hiệu SELL
   vẫn sinh ra và vẫn được ghi log (UI thấy được), chỉ lệnh bị chặn → `reason="no_signal"`,
   `stage="allow_short"`, detail `"SELL blocked: cash market"`. Chọn `no_signal` vì với thị
   trường không có chiều bán thì tín hiệu SELL coi như không tồn tại; từ vựng §8 giữ nguyên
   (bất biến #4). Chặn theo **hướng lệnh**, không phải veto toàn cục — có test cho BUY.
8. **T+2.5 (sai lệch #21)** — `MarketRules` (mới, `order_engine.py`) mang luật sàn cho từng
   symbol; mặc định là hành vi forex/crypto cũ (không settlement, không đáo hạn) nên mọi call
   site trước plan 05 không đổi. Cơ chế: mỗi bar tăng `trading_days_since_entry` khi **ngày
   giao dịch của bar đổi** — tức **đếm theo bar có thật trong dữ liệu**, nên ngày nghỉ lễ (không
   có bar) tự động được bỏ qua, KHÔNG cần lịch nghỉ lễ VN. Được bán khi
   `trading_days_since_entry >= 2` **và** `bar.close_ts` vượt mốc 13:00 ICT của **ngày T+2 đã
   chốt** (`settlement_release_day`, latch một lần khi bộ đếm chạm 2) — không phải 13:00 của
   ngày bar hiện tại. Chốt ngày như vậy vì nếu tính lại theo bar thì trên khung intraday một bar
   sáng ngày T+3 (đóng trước 13:00 của chính nó) lại bị coi là chưa về hàng → lệnh kẹt vĩnh viễn.
   Viết theo mốc thời gian thật nên đúng trên mọi timeframe, không chỉ D1.
   *Giới hạn độ phân giải D1*: một bar D1 phủ cả phiên sáng lẫn phiên chiều, nên toàn bộ bar
   ngày T+2 được coi là đã về hàng — nếu giá chạm SL trong phiên SÁNG ngày T+2 thì backtest vẫn
   ghi exit, dù thực tế phải đợi tới phiên chiều. Sai số tối đa nửa phiên và chỉ ở đúng một bar
   mỗi lệnh; muốn chính xác phải chạy khung intraday (mã đã đúng sẵn cho trường hợp đó).
   Chưa được bán mà giá
   chạm SL/TP → ghi `exit_suppressed_settlement` và **giữ lệnh** (time stop cũng bị bỏ qua:
   không bán được thì không time-stop được).
9. **Đáo hạn VN30F (sai lệch #18)** — `vn30f_expiry(year, month)` trong `core/timeframes.py`
   (thứ Năm tuần 3, thuần lịch). Vị thế còn mở trên bar ngày đáo hạn bị **force-close tại close
   của bar** đó: event `expiry_close` + `CLOSED` kind `EXPIRY`, result phân loại bình thường
   (F2). Thứ tự ưu tiên trong `process_bar`: SL/TP thật > đáo hạn > time stop (chạm SL trong
   phiên đáo hạn thì đó mới là exit thật). *Lưu ý quy ước timestamp*: bar D1 VN được đánh dấu
   theo giờ MỞ phiên (09:00 ICT) nên `close_ts` của bar đáo hạn rơi vào 09:00 ICT phiên KẾ TIẾP
   — đúng quy ước `bar.close_ts` mà time stop đã dùng từ trước, không phải lỗi off-by-one.
10. **Filter `session` với bar D1 (sai lệch có chủ đích)** — quyết định trên khung 1D được lấy
    tại `close` của bar = 00:00 ICT, tức **nằm ngoài mọi cửa sổ phiên** → nếu so thẳng thì
    filter chặn **100% số bar**. Bar D1/1W bao trọn phiên nên chính nó *là* phiên: filter trả
    `passed=True` kèm `values.bar_spans_session=true`. Giới hạn phạm vi **chỉ cho STOCK_VN_***
    để không đụng hành vi/golden của forex (có test canh cả hai chiều). Cửa sổ 2 khoảng
    (09:00–11:30 + 13:00–14:30, D9) vẫn áp dụng nguyên vẹn trên khung intraday — có test
    parametrize 8 mốc giờ, gồm cả giờ nghỉ trưa.
11. **`account_risk` minh bạch hoá** — dòng decision giờ luôn kèm `daily_loss_limit_enabled` và
    `max_concurrent_trades` trong `values` (D10 yêu cầu "ghi `enabled=false` cho minh bạch"),
    thay vì để UI thấy một hạn mức không bao giờ kích mà không rõ vì sao.
12. **`scripts/stitch_vn30f.py`** — nối các file hợp đồng riêng lẻ + lịch roll thành MỘT chuỗi
    back-adjusted (phương pháp **hiệu số/panama**, duyệt ngược từ hợp đồng mới nhất). Chọn hiệu
    số chứ không phải tỷ lệ vì P&L VN30F tuyến tính theo điểm (100.000 VND/điểm) — điều chỉnh
    tỷ lệ sẽ bóp méo khoảng cách điểm, tức bóp méo ATR/SL/R. Giá tuyệt đối của bar cũ **không
    còn là giá giao dịch thật**, nhưng mọi **hiệu giá** (thứ duy nhất chiến lược dùng) là trung
    thực. Engine không biết gì về roll — đúng chủ trương "roll là bước chuẩn bị dữ liệu".

### Kiểm chứng

- `tests/unit/test_stock_vn.py` (35 test): ngày giao dịch VN, lưới D1 UTC-vs-ICT, đáo hạn
  (parametrize 5 tháng gồm tháng bắt đầu bằng thứ Năm), profile 2 chiều, cấm trộn tiền tệ, phiên
  2 khoảng + bypass D1, lô nguyên, T+2.5 (chặn → thả, cuối tuần, TP sau khi thả, và **forex
  không bị chặn**), đáo hạn (force-close, SL thắng đáo hạn, cash không bị force-close).
- `tests/unit/test_stock_vn_decisions.py` (8 test): chặn SELL trên cash **có control là cùng
  setup trên VN30F vẫn `done`**, `lot_below_min` có/không, context không có instrument.
- `tests/integration/test_replay_golden_stock_vn.py` (11 test): golden run cho **mỗi**
  symbol_type trên fixture D1 cố định (600 bar ngày, ~2,4 năm — **đủ dài để EMA89 trên khung
  xác nhận 1W hết warmup**, đúng cảnh báo của plan; file ngắn hơn sẽ kẹt `wait/warmup` mãi mãi).
  Ngoài determinism còn assert luật thị trường **trên bảng trade/trade_event thật**: cash không
  bao giờ mở SELL, cash không bao giờ thoát trước T+2, không vị thế VN30F nào sống qua đáo hạn,
  lô luôn nguyên, `session` không chặn bar nào.
- Histogram lý do trên fixture (600 bar): cash `wait 357 / no_signal 194 / off 41 /
  max_concurrent 6 / done 2`, warmup 88 bar đầu — phễu tín hiệu hẹp đúng như đã ghi ở mục
  "Sửa phễu tín hiệu" (breakout chỉ arm trong regime trend), không phải lỗi chặn hệ thống.
- Golden forex/crypto **không đổi**: profile FOREX rỗng, `test_replay_golden*.py` chạy lại
  xanh, không cần re-pin.

## Plan 07 — Live paper trading: feed thời gian thực, recovery, cảnh báo (2026-07-23)

Bot chạy 24/7 trên dữ liệu thật, khớp lệnh **giả lập** bằng chính `order_engine`. Không có
lệnh thật nào được gửi (đó là plan 08).

### Nguyên tắc trung tâm: live KHÔNG tự quyết định gì

`LiveRunner` chỉ làm hai việc: (a) đưa **bar đã đóng** vào `Feed`, (b) gọi
`Runner.step()` — đúng cái Runner replay dùng. Mọi luật (evaluate-all-decide-after,
fill-at-next-open D6, C11, merged clock tick đa symbol) đến từ cùng một đoạn code, nên
`tests/unit/test_live_runner.py::test_live_matches_replay` **so sánh chuỗi decision của hai
đường bằng nhau tuyệt đối**. Nếu test đó hỏng thì "đã backtest rồi" không còn nói lên điều gì
về hành vi live — đó là lý do tồn tại của cả module.

Hệ quả: **catch-up không phải trường hợp đặc biệt.** Mất 3 bar vì downtime → 3 bar về cùng
lúc → `step()` xử lý tuần tự từng bar, mỗi bar với clock đặt tại close của **chính nó**, nên
quyết định vẫn causal (không nhìn trộm giá mới nhất). Test `miss-3-bars` chạy đúng
`test_live_matches_replay` với 4 bar/lần poll.

### Quyết định

| # | Điểm | Chốt | Lý do |
|---|---|---|---|
| 1 | Recovery sau restart | **Persist state vào DB mỗi bar** (`strategy_state`), KHÔNG re-run `decide()` trên K bar gần nhất | Máy trạng thái retest phụ thuộc đường đi trên cửa sổ không chặn: replay K bar có thể dừng ở trạng thái khác trạng thái từng live, và sai trạng thái retest = âm thầm đổi lệnh nào được vào |
| 2 | Nội dung state | Cả `OpenTrade` **đầy đủ**, không chỉ hàng `trade` | `tp_rules`, `remaining_fraction`, partial đã thực hiện, bộ đếm settlement **không có cột** và không dựng lại được từ hàng trade |
| 3 | Idempotent | Bỏ **cả tick** nếu **bất kỳ** symbol due đã có decision tại `bar_ts` đó (`any`, không phải `all`) | Crash giữa tick đa symbol để lại một phần đã quyết định; chạy lại sẽ **nhân đôi** lệnh. Bỏ tick chỉ mất 1 bar không hành động — phía fail-closed, đúng ưu tiên "ít sự cố nhất" của user |
| 4 | Polling vs websocket | **Polling REST** (`GET /fapi/v1/klines`), ngủ tới `next_bar_close + 5s` | Đơn giản, đủ cho bar ≥ 15m, ít trạng thái lỗi. Websocket là plan 12 |
| 5 | Wallclock | `now_fn` **inject** từ `bot/core/wallclock.py`; `live_runner.py` không bao giờ gọi đồng hồ hệ thống | Bất biến #3 (`test_no_wallclock`) giữ nguyên **không sửa test**, và mọi test live chạy trên clock giả tất định |
| 6 | Cảnh báo | Telegram nếu có `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, ngược lại **log-only** | Thiếu token không được làm hỏng gì; lỗi gửi tin bị nuốt + log — kênh báo sự cố không được trở thành sự cố |
| 7 | DB | `backend/data/live.db` riêng (`BOT_DB_PATH` ghi đè) | Nghịch tay không hỏng lịch sử backtest, và ngược lại |
| 8 | Config | Snapshot lúc tạo run, **đóng băng**; đổi config = dừng + tạo run live mới | Không hot-reload: một run luôn replay được từ đúng một config version |
| 9 | Warmup | **Tính**, không đoán: `warmup_bars_required(tf)` = 300 bar HTF quy ra bar gốc (1D → 300×7 = 2101 bar ngày) | `build_context` xin 300 bar khung chính **và** 300 bar khung cao hơn; HTF là ràng buộc quyết định. Vượt giới hạn 1500 bar/request → backfill phân trang lùi |

### Luật giữ lệnh theo khung (user 2026-07-18, `bot/config/hold_rules.py`)

- **TF ≤ H1**: `time_stop` 8 giờ, `bars=None`, **`after_tp1=true`** — *sai lệch #20 so với C5*
  (C5 tắt time-stop sau TP1). Đây là quyết định rủi ro của user, không phải bug.
  `execution.weekend_flat=true` cho **FOREX** (crypto perpetual chạy 24/7 → không có cửa sổ
  nghỉ để đóng, giữ `false`).
- **TF > H1** (4H/1D/1W): `time_stop.enabled=false`, giữ qua cuối tuần — trùng kết luận
  profile VN (plan 05).
- **Áp dụng ở đâu**: chỉ `live_effective_config()`. Backtest **cố ý không** nhận patch này —
  áp ngược vào lịch sử sẽ đổi hành vi (và golden hash) của mọi run cũ. Thứ tự ưu tiên:
  config toàn cục < profile SYMBOL_TYPE < **hold rules** < `overrides` per-symbol, nên
  override thủ công vẫn thắng.
- **`weekend_flat` là field CONFIG** (`execution.weekend_flat`, default `false`), không phải
  logic suy ra trong engine — nhờ vậy backtest replay đúng config snapshot của một run live
  sẽ tái hiện y hệt hành vi live, và mọi golden hash cũ không đổi (default `false`).
  Engine đóng tại close của bar cuối tuần (Thứ Sáu ≥ 17:00 America/New_York = đúng mốc
  rollover C3), event `weekend_close`, kết quả phân loại bình thường theo F2.
- `trade.timeframe` (cột mới) ghi khung lúc mở lệnh để audit không phụ thuộc config đổi sau.

### Sai lệch mới

20. **Time stop 8h vẫn chạy sau TP1 khi TF ≤ H1** — ngược C5, theo quyết định user
    2026-07-18 (xem bảng trên).
21. **Không mô hình hoá funding fee** của perpetual — `order_engine` tính P&L thuần theo giá.
    Kết quả paper crypto khung H4/D1 vì thế lệch so với thật; plan 12a thêm funding, và plan 08
    coi 12a là điều kiện tiên quyết để tin số liệu paper crypto.
22. **Không mô hình hoá margin/liquidation** cho futures — plan 12b, **bắt buộc** trước khi
    plan 08 arm lệnh thật cho crypto.

### Venue & phạm vi

Binance USDⓈ-M Futures (`fapi/v1/klines`, công khai, không cần API key). Testnet dùng chung
schema → đổi mỗi base URL (`--testnet`). `BinanceFuturesFeed` chỉ nhả bar khi
`open_ts + tf_duration <= now` (**không** dùng `close_time` của venue, vốn là
`open + interval − 1ms` và sẽ làm bar cuối trông như đã đóng sớm 1ms).
FOREX (plan 10) và VN30F bị **từ chối thẳng** khi tạo run live: DNSE Entrade không có endpoint
nến, nên VN30F cần nguồn market-data do user chỉ định — viết `BarSource` thứ hai theo cùng
interface, phần còn lại không đổi.

**Một process cho cả danh mục** (rà lại 2026-07-18): `MAX_CONCURRENT_TRADES`, daily-loss-limit
và `max_total_open_risk_pct` là trần **toàn tài khoản**; mỗi symbol một process sẽ vô hiệu hoá
toàn bộ chúng. `--symbol` chỉ là override debug.

### API & UI

`GET /api/live/status` mở DB live **read-only** (WAL cho phép đọc song song, không chặn quyết
định giao dịch): lag = wallclock − close bar cuối, feed_state, uptime, equity. Không có DB /
không có run live → `running: false` (câu trả lời bình thường, không phải lỗi).
`POST /api/live/stop` là **ghi duy nhất** API thực hiện lên run live: đặt `run.stop_requested`,
cờ LiveRunner kiểm mỗi vòng lặp. Badge LIVE trên nav hiện lag, đổi màu theo độ trễ
(>5 phút vàng, >15 phút đỏ) và đỏ khi feed `degraded`.

### Test

- `test_live_feed.py` (16): bar chưa đóng bị loại, biên `open+dur == now` thuộc phía ĐÃ đóng,
  retry/backoff+jitter, lỗi venue dạng `{"code":...}`, backfill phân trang, `next_close_after`
  cho cả 5 khung. Không test nào mở socket.
- `test_live_runner.py` (8): **live == replay** (1 bar/poll và 4 bar/poll = catch-up sau khi
  mất 3 bar), restart giữa chừng dựng lại từ DB rồi chạy tiếp vẫn bằng replay, khôi phục lệnh
  đang mở nguyên vẹn, tick trùng bị bỏ thay vì quyết định hai lần, feed hỏng → `degraded` →
  hồi phục (mỗi chuyển trạng thái đúng 1 alert), `stop_requested` dừng vòng lặp.
- `test_hold_rules.py` (13), `test_notify.py` (8), `test_live_factory.py` (9),
  `tests/api/test_live_status.py` (6).
- Golden hash forex/crypto/VN **không đổi** (default `weekend_flat=false`, hold rules chỉ
  áp cho live) — `test_replay_golden*.py` chạy lại xanh, không re-pin.

## Plan 07b — Dữ liệu thị trường DNSE OpenAPI: spot + phái sinh VN (2026-07-23)

Nguồn: <https://developers.dnse.com.vn/docs/guide/market-data/connect> (WebSocket) và
<https://developers.dnse.com.vn/docs/dnse/get-ohlc-history> (REST lịch sử OHLC).

**Vượt qua ghi chú cũ của plan 07** (mục "Venue & phạm vi": *"DNSE Entrade không có
endpoint nến … VN30F bị từ chối thẳng khi tạo run live"*). Ghi chú đó nói về **Entrade
API** (hdsd2.entrade.com.vn), vốn chỉ có giao dịch/tài sản. **DNSE OpenAPI là hệ thống
khác** và có đầy đủ OHLC cho `STOCK` (cổ phiếu), `DERIVATIVE` (VN30F) và `INDEX`
(VNINDEX/VN30). `SUPPORTED_LIVE_SYMBOL_TYPES` giờ là
`{CRYPTO, STOCK_VN_CASH, STOCK_VN_DERIV}`; chỉ FOREX còn bị từ chối (plan 10).

### Quyết định

| # | Điểm | Chốt | Lý do |
|---|---|---|---|
| 1 | REST hay WebSocket | **REST `GET /price/ohlc`**, polling — giống hệt quyết định #4 của plan 07 cho Binance | Engine chỉ ăn **nến đã đóng** trên lưới 1D (profile VN ép 1D); polling ít trạng thái lỗi hơn socket có state, và quan trọng nhất: cùng `BarSource` ⇒ `test_live_matches_replay` vẫn có nghĩa. Channel `ohlc_closed.{resolution}.{encoding}` là tối ưu độ trễ, để plan 12 (giao thức đã ghi đủ ở cuối mục này) |
| 2 | Đơn vị giá cổ phiếu | **Nhân 1000** (`STOCK_PRICE_SCALE`) | DNSE báo HPG = `24.35` nghĩa là 24 350 VND. Mọi `instruments.yaml`, fixture và dataset trong repo là **VND nguyên** (`hpg_1d_sample.csv` mở ở 27000.0, `pip=1.0` VND). Không scale = sai số **1000×** trên sizing và P&L. `DERIVATIVE` (điểm chỉ số, 1881.2) và `INDEX` **không** scale |
| 3 | Mốc thời gian nến D1 | **Neo về 09:00 ICT (= 02:00 UTC) của ngày giao dịch ICT** | Đúng quy ước mọi dataset VN trong repo, và là mốc plan 05 §9 dựa vào ("`close_ts` của bar D1 rơi vào 09:00 ICT phiên KẾ TIẾP"). Chuẩn hoá đi qua **ngày lịch ICT** nên **idempotent** với mọi quy ước venue có thể dùng (00:00 ICT / 00:00 UTC / 09:00 ICT / 14:45 ICT đều ra cùng một ngày) — có test parametrize 4 mốc |
| 4 | "Nến đã đóng" | Giữ nguyên `open_ts + tf_duration <= now` (C11), **không** đặc cách VN | Với D1 VN, nến hôm nay chỉ thấy được lúc 09:00 ICT hôm sau — đúng lúc nến kế tiếp mở, nên fill D6 rơi vào open phiên đó. Sửa thành 14:45 ICT sẽ làm live **lệch khỏi mọi backtest đã chạy** |
| 5 | Khung thời gian | 15m→`15`, 1H→`1H`, 1D→`1D`, 1W→`1W`. **Không có 4H** | DNSE chỉ có 1/3/5/15/30/1H/1D/1W. Trùng với quyết định plan 05 #2 (VN chỉ D1, không định nghĩa H4 trên phiên VN). Override sai khung → `FeedError` ngay, không âm thầm lấy khung khác |
| 6 | Credentials | `DNSE_API_KEY` / `DNSE_API_SECRET` từ env; thiếu → `ConfigError` **trước khi tạo run** | Fail-closed (ưu tiên "ít sự cố nhất"). Secret không bao giờ vào log/repr (có test) |
| 7 | Lịch sử ngắn không phải lỗi | `backfill` trả về ít hơn `warmup_bars_required` mà **không raise** | VN30F1M mới niêm yết 2017 ⇒ xin 2100 bar D1 (~8,4 năm) có thể không đủ. Engine đã trả `wait/warmup` khi indicator còn NaN (C12) — đúng hướng fail-closed |
| 8 | Ký REST | HMAC-SHA256 theo HTTP Signature; gửi **cả** `Date` lẫn `X-Aux-Date` | Trang "Xác thực" đặt tên header là `Date`, trang endpoint OHLC đặt tên `X-Aux-Date`. Gửi cả hai thoả mãn cả hai cách đọc và không tốn gì |

### Chi tiết ký REST (`bot/data/dnse_feed.py`)

Signing string (thứ tự dòng và chữ thường là bắt buộc, sai là bị từ chối ngay):

```
(request-target): get /price/ohlc
date: Fri, 15 May 2026 07:11:30 +0000
nonce: <uuid4 hex 32 ký tự>
```

→ HMAC-SHA256(API Secret, chuỗi trên) → Base64 → URL-encode **chỉ** 3 ký tự `+ / =`
(không double-encode) → header:

```
X-Signature: Signature keyId="{key}",algorithm="hmac-sha256",headers="(request-target) date",signature="{enc}",nonce="{nonce}"
```

`Date` lệch quá **±1 phút** so với giờ DNSE → từ chối; nonce **không được tái dùng**, nên
**mỗi lần retry ký lại** (có test đếm 3 chữ ký khác nhau cho 3 lần thử).

### ⚠️ Cần xác minh khi user có API key (chưa kiểm được vì không có credentials)

1. **`(request-target)` có kèm query string không?** Ví dụ trong docs (`get /accounts`)
   không có query, nhưng `/price/ohlc` luôn có 5 tham số. Mặc định **chỉ ký path**; đặt
   `DNSE_SIGN_QUERY=1` để chuyển sang cách đọc draft-cavage (path + query) nếu server từ
   chối. Đây là điểm dễ sai nhất — thử trước tiên khi gặp `AUTH_FAILED`.
2. **`resolution` viết hoa hay thường?** Trang enum ghi `1H`, trang endpoint ghi `1h`.
   Đang dùng `1H`; đổi ở `RESOLUTION_BY_TIMEFRAME` nếu 400.
3. **Quy ước timestamp nến D1 thật của venue** — chuẩn hoá đã idempotent cho mọi khả
   năng hợp lý (quyết định #3), nhưng vẫn nên đối chiếu một ngày thật với
   `hpg_1d_sample.csv` (02:00Z) sau lần fetch đầu tiên.
4. **Hệ số 1000 cho cổ phiếu** (quyết định #2) — kiểm bằng mắt: HPG phải ra ~24 000–30 000
   VND, không phải ~24–30. Đây là sai số nguy hiểm nhất nếu sai chiều.
5. **Header tên `Date` hay `X-Aux-Date`** — nếu server phàn nàn về header thừa thì bỏ bớt.

### Giới hạn đã biết (không sửa ở đây)

- **`VN30F1M` live là chuỗi front-month có bước nhảy tại roll** — venue trả alias
  cuộn tháng, không back-adjust. Không nguy hiểm cho vị thế (plan 05 §9 đã force-close tại
  đáo hạn nên không lệnh nào sống qua roll), nhưng **ATR/EMA sẽ nuốt một gap** mỗi tháng.
  Backtest nên dùng `scripts/stitch_vn30f.py` (panama/hiệu số) như trước.
- **Không mô hình tick HOSE / trần-sàn ±7%** — sai lệch #16–17 giữ nguyên; giá DNSE là giá
  thật nên đã đúng bước giá, nhưng engine vẫn không *ép* SL/TP về bước giá hợp lệ.
- **Chỉ REST, chưa dùng WebSocket** — độ trễ nhận nến đóng phụ thuộc chu kỳ poll
  (`LiveRunner` ngủ tối đa 30s), quá đủ cho D1.
- **`ohlc_closed` WS cho khung intraday** sẽ là đường nâng cấp khi nào chạy 15m/1H.

### Giao thức WebSocket (ghi lại để plan sau không phải đọc docs lại)

`wss://ws-openapi.dnse.com.vn/v1/stream?encoding=json|msgpack` →
`welcome` (kèm `session_id`, phải auth trong 30s) →
`{"action":"auth","api_key":…,"signature":HMAC-SHA256(secret, "{api_key}:{timestamp}:{nonce}").hexdigest(),"timestamp":<giây>,"nonce":<micro giây>}`
→ `auth_success` → `{"action":"subscribe","channels":[{"name":"ohlc_closed.1D.json","symbols":["HPG"]}]}`
→ `subscribed`. **Lưu ý**: với phái sinh truyền `symbolType` (`VN30F1M`) chứ không phải mã
hợp đồng (`41I1G4000`). Server ping mỗi 3 phút, client phải `pong` trong 60s (nên tự ping
mỗi 25s). Kết nối **hết hạn sau 8 giờ** (`connection_expired` + close 1008) — reconnect là
hành vi bình thường, backoff 1s→60s. Phân loại message: chỉ coi là control khi `action` ∈
`{welcome, auth_success, subscribed, unsubscribed, ping, pong, connection_expired, error}`,
còn lại là data (nhận biết qua trường `T`). Payload `ohlc_closed` giống hệt REST về ngữ
nghĩa nhưng dạng object đơn (`time/open/high/low/close/volume/symbol/resolution/type`) —
**vẫn phải áp cùng hệ số 1000 và cùng chuẩn hoá mốc D1** ở trên.

### Kiểm chứng

- `tests/unit/test_dnse_feed.py` (35 test): signing string đúng layout docs, chữ ký
  verify được bằng HMAC dựng tay, nonce mới mỗi lần retry, thiếu credentials fail-closed,
  neo D1 idempotent qua 4 quy ước venue, ICT không có DST, nến đang hình thành bị loại,
  biên `open+dur == now` thuộc phía đã đóng, scale 1000 cho STOCK và **không** scale cho
  DERIVATIVE/INDEX, 4H bị từ chối, payload lệch độ dài mảng bị từ chối, backfill đi lùi
  đúng hướng / dừng sau 2 cửa sổ rỗng / lịch sử ngắn không raise, lịch poll cho D1/1W/15m.
  Không test nào mở socket hay cần credentials thật.
- `tests/unit/test_live_factory.py` (+4): VN cash & deriv được chấp nhận live (khung 1D
  từ profile), đường wiring thật dựng `DnseOhlcFeed` đúng `type` và ghi venue DNSE vào
  dataset id (để guard đổi-venue lúc resume so đúng chỗ), thiếu key → `ConfigError`.
- Golden hash **không đổi**: module này chỉ là nguồn dữ liệu mới, không đụng engine.
