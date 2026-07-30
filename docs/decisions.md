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

## Plan 13 — Alert center: Telegram + toast web UI + log DB (2026-07-23)

Yêu cầu user 2026-07-18: **mọi sự kiện quan trọng vừa alert Telegram, vừa toast trên web
UI, vừa log lại ở backend**. Plan 07 đã có nửa Telegram (`bot/notify.py`); plan này biến
nó thành một event bus chung, thêm bảng DB và giao diện.

### 1. Danh mục event đã chốt (`bot/alerts/codes.py`)

Đúng bảng của plan 13, cộng một mã: **`runner_crashed` (CRITICAL)** — plan 07 đã có
`LiveAlerts.crashed()` nhưng plan 13 chỉ liệt kê `runner_stopped`; crash và stop là hai
việc khác nhau (một cái tự phục hồi qua supervisor, một cái là chủ ý) nên tách mã.

| Nhóm | Mã | Level |
|---|---|---|
| Vòng đời lệnh | `trade_pending` (Telegram **tắt** mặc định), `trade_opened`, `tp1_hit`, `trade_cancelled`, `trade_closed` | INFO |
| Rủi ro tài khoản | `daily_loss_limit`, `equity_multiplier`, `drawdown_warn` | WARN |
| | `drawdown_critical` | CRITICAL |
| Sức khoẻ hệ thống | `feed_degraded`, `runner_stopped` / `feed_recovered`, `runner_started`, `daily_summary` | WARN / INFO |
| Broker (plan 08) | `order_error` (ERROR), `naked_position_closed`, `circuit_breaker`, `desynced` (CRITICAL) | — |
| Ảnh chart (plan 14) | `snapshot_error` | WARN |

Bốn mã của plan 08 và một mã của plan 14 **đã có trong catalogue nhưng chưa được phát**:
mức độ nghiêm trọng là quyết định của user (2026-07-18 đợt 3), ghi một lần ở đây rẻ hơn
là mỗi plan tự nghĩ lại. Plan 08 chỉ cần gọi `alerts.emit`, không phải định nghĩa lại.

`drawdown_critical` ở đây **chỉ báo**; hành động "tự chuyển paper" thuộc plan 08 §2
(live hiện tại vốn đã là paper, không có gì để chuyển).

### 2. Alert log là **database riêng** (`backend/data/alerts.db`)

Quyết định đáng kể nhất của plan này. Lý do: run backtest ghi `runtime.db`, run live ghi
`live.db` (plan 07 §3 cố tình tách), nhưng plan 13 yêu cầu **một** con trỏ
`GET /api/alerts?since_id=` — mà một con trỏ chỉ có nghĩa trên **một** không gian id.
Ba phương án:

1. Bảng `alert` trong cả hai DB, API gộp hai nguồn → `since_id` phải thành cặp con trỏ,
   frontend phải hiểu "id" nào thuộc DB nào. Rối và dễ mất alert.
2. Chỉ ghi alert cho live → mất nửa "replay" của Definition of Done.
3. **DB riêng, cả hai tiến trình cùng append.** Chọn phương án này.

Hệ quả: (a) API **được phép ghi** vào đây (đánh dấu đã đọc) mà không phá quy tắc plan 07
"API không bao giờ ghi vào DB của run live" — đây không phải DB của run nào cả;
(b) `run_id` **không phải khoá ngoại**, nó được định danh kèm cột `source`
(`live` / `backtest`), vì run #3 của `live.db` và run #3 của `runtime.db` là hai run khác
nhau. WAL + `busy_timeout` cho phép hai tiến trình ghi song song. Đường dẫn đổi được bằng
`BOT_ALERTS_DB_PATH`; app API mặc định lấy file `alerts.db` **cạnh** DB run của nó, nên
test (tmp_path) tự động cách ly.

### 3. Schema có thêm 3 cột ngoài plan

Plan ghi `alert(id, run_id, ts, level, code, title, body_json, sent_telegram, read)`.
Thực tế cần thêm:

- **`telegram_status`** (`pending|sent|logged|failed|suppressed|muted`) — vì plan yêu cầu
  đồng thời hai hành vi mà `sent_telegram=false` không phân biệt được: *"lỗi gửi → thử lại
  ở lần emit sau"* và *"trong cooldown → cố tình không gửi"*. Nếu chỉ có cờ boolean thì
  retry sẽ phá cooldown. `sent_telegram` vẫn giữ nguyên ngữ nghĩa của plan: **đã tới
  điện thoại**. Vì thế có thêm trạng thái `logged` — không có token thì `LogNotifier`
  nhận dòng đó nhưng **không ai nhận được tin**; nếu tính là `sent` thì UI sẽ vẽ icon
  ✈️ cho một tin chưa bao giờ rời khỏi máy. `Notifier` có thuộc tính `remote: bool` để
  bus phân biệt (thay vì `isinstance`). `logged` vẫn tính là "đã giao" cho cooldown, để
  bật token về sau không làm đổi nhịp gộp tin.
- **`dedupe_key`** — khoá gộp (thường là symbol, hoặc trading day cho
  `daily_loss_limit`). Cooldown đo từ lần **gửi thành công** gần nhất của
  (`code`, `dedupe_key`); dòng bị suppress không tự gia hạn cooldown của chính nó.
- **`source`** — xem mục 2.

### 4. Thứ tự ưu tiên trong `emit()` (bất biến của plan này)

1. **DB luôn ghi** — kể cả khi Telegram tắt/muted/lỗi. Không có công tắc config nào làm
   một event biến mất; `AlertsConfig` chỉ điều chỉnh **kênh Telegram**.
2. Telegram nếu có token + đạt ngưỡng + không bị mute + ngoài cooldown.
3. **CRITICAL không bao giờ bị gộp, mute hay chặn ngưỡng.**
4. **`emit()` không bao giờ ném exception** — `except Exception` rộng ở đây là cố ý:
   runner gọi nó ngay trong vòng lặp giao dịch, một alert giết được bot thì tệ hơn là
   không có alert. Test `test_a_broken_db_never_escapes_emit` khoá hành vi này.

`Notifier.send` đổi kiểu trả về `None → bool` để bus phân biệt gửi được / gửi lỗi (vẫn
không ném ra ngoài như plan 07).

### 5. Giữ bất biến #6 (một chiều phụ thuộc)

`bot/engine/*` **không được import `bot/alerts`**. Cách giữ: tách formatter khỏi
transport.

- `bot.notify.LiveAlerts` = **formatter** (event → code/level/title/body). Engine dùng
  cái này, như plan 07.
- `bot.alerts.bus.AlertBus` = **transport** (DB + Telegram + cooldown), thoả protocol
  `notify.AlertEmitter`.
- Composition root quyết định: `bot/cli.py` truyền `alerts_factory=` vào
  `build_live_session` (nhận `(run_id, cfg)` — chỗ đầu tiên biết cả hai, và run **resume**
  phải lấy ngưỡng từ config đã đóng băng của nó, không phải config hôm nay); API truyền
  `alerts_conn` vào `RunnerService`. Không có factory → đúng hành vi plan 07 (log-only).
- `bot/engine/announce.py` gom ánh xạ `StepSummary → alert` dùng chung cho cả live runner
  và runner replay của API, để hai đường không trôi khỏi nhau.
- `tests/unit/test_dependency_direction.py` kiểm bằng **AST** (không grep chuỗi, vì có
  vài docstring nhắc tới `bot.alerts` một cách chính đáng) + một test ngược lại: phải có
  ai đó *thực sự* import `bot.alerts`, nếu không test kia xanh vì tính năng chưa được nối.

### 6. Telegram cho run replay: tắt

`RunnerService` dựng bus với `notifier=None` (mọi dòng là `muted`). Replay 5000 nến sẽ
bắn hàng chục tin về điện thoại cho những lệnh đã xảy ra trong quá khứ. DB + toast vẫn đủ
cho Definition of Done ("chạy replay: mở/đóng lệnh sinh alert trong DB, toast hiện trên web").

### 7. Frontend: **tự viết toast**, không thêm thư viện

Plan cho phép chọn sonner / react-hot-toast / tự viết — chọn **tự viết**
(`components/AlertCenter.tsx` + `hooks/useAlertCenter.ts`, ~250 dòng cả CSS). Lý do: toàn
bộ bề mặt cần dùng là "một stack cố định + TTL theo level", nó tái dùng được biến CSS sẵn
có nên light/dark chạy đúng miễn phí, và app này mới có đúng 3 dependency runtime
(react, router, axios) — thêm một cái nữa cho 150 dòng là không đáng.

Hai chi tiết hành vi:

- **Lần poll đầu KHÔNG toast gì** — chỉ học con trỏ. Mở dashboard sau một tuần mà bị chôn
  dưới một tuần lịch sử sẽ dạy người dùng thói quen bấm tắt không đọc. Lịch sử vẫn nằm
  trong dropdown chuông.
- **TTL theo level**: INFO 6s, WARN 20s, ERROR/CRITICAL **không tự tắt** (phải bấm đóng).
- `max_id` trong response lấy từ bảng chứ không từ trang kết quả, để client đang lọc
  `level=CRITICAL` không quét lại cùng dải id mãi mãi.

### 8. Kiểm chứng

- `tests/unit/test_alerts_bus.py` (19 test): DB luôn có dòng kể cả khi không có Telegram;
  cooldown gộp theo (code, key) và hết hạn đúng; **CRITICAL không bị gộp/mute/chặn ngưỡng**;
  `trade_pending` mặc định không gửi Telegram nhưng vẫn được log; exception từ Telegram và
  cả DB hỏng đều không thoát khỏi `emit`; retry gửi lại đúng backlog; `equity_multiplier`
  chỉ nói khi hệ số **đổi**; mã lạ vẫn được log ở mức WARN. Không test nào mở socket.
- `tests/api/test_alerts.py` (8 test): danh sách newest-first, `since_id`, lọc level,
  con trỏ vẫn tiến khi trang rỗng, `limit` bị chặn 422, đánh dấu đọc idempotent + list
  rỗng **không** phải "đọc tất cả", và một run replay thật sinh đủ
  `trade_pending`/`trade_opened`/`trade_closed`.
- `tests/unit/test_dependency_direction.py`: bất biến #6.
- Golden hash **không đổi**: `StepSummary` chỉ được **thêm** hai trường quan sát
  (`opened_trade_db_id`, `risk_multiplier`); không có nhánh quyết định nào đọc chúng.

## Plan 14 — Chart snapshot: ảnh ~100 nến lúc mở/đóng lệnh (2026-07-24)

### 1. Kích thước ảnh + retention: chốt theo đề xuất của plan

**1200×700, dpi 100** (`bot/report/snapshot.py`, `FIGSIZE=(12,7)`, `DPI=100`) — PNG thực
đo ra ~55–90KB/ảnh trên dữ liệu mẫu, đúng dải đề xuất. **Retention gắn theo run**: không
có job xoá theo ngày; `RunnerService.delete_run` chưa đụng tới `data/snapshots/{run_id}/`
(việc dọn thư mục khi xoá run để lại cho lần chạm tới `delete_run`, chưa phải yêu cầu của
plan này — chưa có test canh cho phần đó).

### 2. Không thêm cột DB cho open/close — TRỪ MỘT: `trade.range_high`/`range_low`

Đường dẫn ảnh đúng như plan tả (theo quy ước `{run_id}/{trade_id}_{at}.png`, không cần
cột DB). Nhưng range breakout tại thời điểm tín hiệu (`Signal.range_high/range_low`) chỉ
tồn tại **trong bộ nhớ** lúc quyết định — `breakout_state` trong DB bị ghi đè mỗi tick nên
không dùng lại được sau khi lệnh đã mở. Thêm 2 cột nullable vào `trade` (migration
`006_snapshot.sql`), set ở `Runner.step()` lúc `insert_trade` (NULL cho mean reversion).
Đây là lựa chọn rẻ hơn nhiều so với tái dựng lịch sử `breakout_state` cho một lần vẽ ảnh.

### 3. Vị trí trong cây package: `bot/report/`, không phải `bot/engine/`

Đúng bất biến #6 của plan (matplotlib/mplfinance **không** được lọt vào
indicators/filters/strategies hay vòng lặp quyết định của engine — `runner.py`,
`main_loop.py`, `order_engine.py`, `context.py`, `decision_log.py`, ...).
`bot.engine.live_runner` là **ngoại lệ duy nhất** trong `bot/engine/`: nó là "tầng runner"
plan gọi tên tường minh ("tầng runner gọi sau sự kiện fill/close"), và nó chỉ *quan sát*
kết quả `Runner.step()` đã commit — không quyết định gì. `tests/unit/
test_no_matplotlib_in_engine.py` canh việc này bằng AST (không phải grep chuỗi), loại trừ
đúng một file (`live_runner.py`) khỏi danh sách cấm.

### 4. Xác định trade nào vừa fill/close: bắt `trade_db_id` TRƯỚC khi gọi `runner.step()`

`Runner.step()` xoá `SymbolContext.trade_db_id` ngay khi lệnh đóng, nên đọc nó SAU step()
là quá trễ. `LiveRunner.drain()` chụp `pre_trade_ids = {symbol: trade_db_id}` ngay trước
mỗi lần gọi `step()`; `_capture_snapshots` dùng map đó để biết event FILLED/closed thuộc
trade nào — kể cả trường hợp một lệnh fill VÀ đóng trong cùng một tick (cùng id cho cả
hai ảnh).

### 5. Marker "signal bar": suy từ bảng `decision`, không thêm cột mới

Quyết định tạo lệnh (`reason='done', stage='place_order'`) là dòng `decision` duy nhất có
`trade_id` khớp và `bar_ts_utc` chính là nến tín hiệu — `repo.signal_decision_for_trade`
lấy dòng đó thay vì lưu thêm timestamp. Marker "BE" tách riêng khỏi SL bị bỏ (YAGNI): cột
`sl_price` tại thời điểm đóng lệnh đã tự nhiên phản ánh breakeven nếu TP1 đã chạm (Runner
chỉ ghi `sl_price` lúc fill và lúc đóng, không ghi mỗi bar) — vẽ một đường SL là đủ, không
cần phân biệt "SL gốc" và "SL đã dời BE" trên cùng một ảnh tĩnh.

### 6. API: một endpoint, không tách static mount + on-demand riêng

Plan gợi ý static mount (`GET /api/snapshots/{run_id}/{filename}`) cho ảnh có sẵn, cộng
endpoint on-demand riêng cho backtest. Gộp thành **một** `GET /api/trades/{id}/snapshot?
at=open|close`. Frontend không cần biết ảnh có sẵn hay vừa render.

**Sửa bug (2026-07-24): KHÔNG serve file trên đĩa cho run backtest.** Bản đầu serve thẳng
`snapshots/{run_id}/{trade_id}_{at}.png` nếu tồn tại. Nhưng `run_id`/`trade_id` chỉ duy
nhất *trong một vòng đời DB*: khi `runtime.db` bị tạo lại (rất hay gặp lúc dev) hoặc số id
trùng với run cũ của symbol khác, file cũ còn sót lại bị serve cho lệnh mới — biểu hiện là
"chart EURUSD mà hiện giá/nến BTCUSDT". Vì render backtest **xác định** (cùng dataset + config
version → đúng frame engine đã thấy), nay `render_trade_snapshot()` luôn render lại mỗi lần,
không bao giờ tin file cache. Chỉ run **live/paper** mới serve file eager (dataset là stream
sàn, không có nến lưu để render lại) — quyết định live-vs-backtest gói gọn trong
`render_trade_snapshot()`, endpoint chỉ gọi service. Regression:
`test_on_demand_snapshot_ignores_a_stale_file_on_disk` cắm sẵn file rác rồi khẳng định
response là PNG mới (magic bytes), không phải bytes rác.

### 7. Backtest/replay: mặc định KHÔNG chụp eager — giữ nguyên như plan, không thêm flag

Cờ "bật eager cho backtest" trong plan đánh dấu ❓ tuỳ chọn — không có yêu cầu cụ thể nên
không thêm (YAGNI); on-demand render tái tạo đúng frame xác định (cùng dataset, cùng
config version) nên không mất gì so với chụp eager.

### 8. Kiểm chứng

- `tests/unit/test_snapshot.py`: `render_snapshot` từ frame cố định (seed) ra PNG tồn tại,
  size > 0; số bar vẽ bị cắt đúng `max_bars`; level nằm trong dải giá hợp lý; frame rỗng
  → `ValueError`. `capture_trade_snapshot` dựng đúng ảnh từ một `trade` giả trong DB
  in-memory; trade không tồn tại → `ValueError`.
- `tests/unit/test_live_runner_snapshot.py`: một run live/paper đầy đủ qua `LiveRunner`
  sinh đủ `{trade_id}_open.png` + `{trade_id}_close.png` cho mọi lệnh CLOSED; renderer bị
  monkeypatch ném exception → run vẫn xử lý hết lệnh, alert `snapshot_error` xuất hiện
  trong `LogNotifier.sent` (không throw ra khỏi `drain()`).
- `tests/api/test_trade_snapshot.py`: on-demand render ra `image/png` cho một trade
  backtest CLOSED thật (open lẫn close); gọi lần hai vẫn ra PNG hợp lệ (render lại, không
  stale); file rác trên đĩa bị bỏ qua (regression bug symbol sai); trade không tồn tại →
  404; `at` sai giá trị → 422.
- `tests/unit/test_no_matplotlib_in_engine.py`: AST-walk `indicators/filters/strategies`
  + `engine` (trừ `live_runner.py`) không import `matplotlib`/`mplfinance`.
- `mypy --strict` + `ruff` xanh trên `bot/report/` (thêm override `mplfinance.*` vào
  `[[tool.mypy.overrides]]` vì thư viện không có type stub).

## Plan 03 (bổ sung) — Overlay EMA34/89 lên chart nến Dashboard (2026-07-24)

Chart nến `lightweight-charts` trước chỉ vẽ OHLC + markers, không có tín hiệu chỉ báo.
Thêm 2 đường EMA34 (xanh) / EMA89 (cam) — cùng bảng màu với ảnh snapshot plan 14.

- **Tính server-side, trên toàn bộ lịch sử đã đóng**, không tính client-side trên cửa sổ
  trả về. EMA đệ quy: giá trị ở nến t phụ thuộc chuỗi từ đầu (seed bằng SMA `period` nến
  đầu). Nếu frontend chỉ nhận ~1000 nến rồi tự tính, EMA ở mép trái sẽ sai. Nên `run_bars`
  tính `ema()` (chính hàm engine dùng) trên `closed` = mọi nến đã đóng tới clock hiện tại
  (đúng C11 no-lookahead), rồi mới cắt theo `from/to/limit`; trả thêm cột `ema34`/`ema89`
  (nullable — nến còn trong warmup SMA trả `null`, frontend bỏ qua khi vẽ).
- **Causal ⇒ no-lookahead giữ nguyên**: EMA chỉ nhìn quá khứ nên step thêm 1 nến không đổi
  giá trị các nến cũ — `test_bars_no_lookahead_grows_one_candle_per_step` vẫn khẳng định
  `bars2[:N] == bars` sau khi thêm cột EMA.
- `BarOut` thêm `ema34`/`ema89: float | None`; `CandleChart.tsx` vẽ 2 `LineSeries`.

## BRB v2 — Breakout → Retest → Breakout + ma trận điểm số (2026-07-26)

Nguyên nhân gốc của "SL quét trong 1 nến / win<loss": chiến lược cũ (`breakout_retest.py`)
vào lệnh NGAY tại nến retest ⇒ entry ≈ `range_high`/`range_low`, SL neo `retest_low/high ∓
0.5×ATR` ⇒ 1R ≈ 0.5×ATR, một nến biến động bình thường (~1×ATR) quét trọn 1R. `docs/
spec_v2.md` (BRB) sửa gốc: chỉ vào lệnh khi giá phá **Peak1** (đỉnh xung lực ≥ 1×ATR trên
range) ⇒ entry cách xa SL ⇒ 1R lớn hơn hẳn. Người dùng chốt (2026-07-26): làm cả hai — xây
BRB đầy đủ **và** thêm guard khoảng cách SL trực tiếp — thay vì chọn một trong hai.

### Quyết định giữ-invariant (giải mâu thuẫn spec_v2 vs engine)

| spec_v2 | Engine invariant | Quyết định |
|---|---|---|
| Vào lệnh tại **close** nến breakout-2 | D6/C2: quyết ở close `[-1]`, khớp ở open `[+1]` | **Giữ D6** — không có lệnh chờ tại `Peak1+2pip` (engine không có stop-order) |
| TP1 = 1.618×Sóng1 (measured move) | TP là R-multiple chốt lúc fill (deviation #7) | **Giữ R-multiple** (`tp1_r=1.5` mặc định); measured-move tuyệt đối để follow-up |
| Retest sai số ±0.3% | D5: retest theo ATR (mult 0.25) | **Giữ ATR mode** (đã tốt hơn D5) |
| SL cap 2.0×ATR, risk ≤2% | Chưa có cap khoảng cách SL | **Thêm** `min_stop_atr_mult`/`max_sl_atr_mult` (guard chống-1-nến trực tiếp, độc lập BRB) |
| Trailing Fractal cho TP2 | Engine: breakeven sau TP1 + TP2 = R cố định | **Giữ TP2 = R cố định**; fractal trailing để follow-up (đụng `order_engine.process_bar`) |

### Triển khai

1. **Máy trạng thái 4 pha** (`strategies/breakout_retest.py`, `strategies/base.py`):
   `NONE → AWAITING_PEAK → AWAITING_RETEST → AWAITING_BREAKOUT2 → signal`. `BreakoutState`
   thêm `peak1`, `retest_low`, `retest_high`; `bars_waited` giờ đếm theo bar **trong pha
   hiện tại** (reset về 0 mỗi lần chuyển pha), không còn là bộ đếm toàn cục.
   `breakout.require_second_breakout` (mặc định **true**) chọn nhánh BRB; `false` fallback
   nguyên máy trạng thái v1.2 (retest = entry, `Signal.peak1` = `None`) để A/B so sánh và
   để các test không liên quan tới BRB (settlement/expiry/allow_short/live-runner
   plumbing...) không phải tune lại tham số BRB — xem mục "Test fixtures" bên dưới.
2. **Ma trận điểm số** (`strategies/scoring.py`, MỚI, pure) — A1/A2/A4/B1/B2/B3/C1 tính
   trực tiếp từ series `FilterContext` tại bar breakout-2; B1/B2/B3 (pin bar/engulfing/bóng
   dài tại nến retest) định vị lại nến retest qua `Signal.retest_bars_ago` (bar offset, MỚI
   trên `Signal`) thay vì mang nguyên nến retest xuyên suốt state/Signal. **A3 (volume)**
   chỉ cộng vào `max_available` khi `filters.volume.enabled` (FOREX mặc định false, VN
   profile true) — ngưỡng là **tỉ lệ** `total/max_available ≥ scoring_threshold_ratio`
   (mặc định 0.66 ≈ 8/12), không phải điểm tuyệt đối, để FOREX (max=10) và VN (max=12) so
   được cùng thang. `indicators/candle.py` thêm `is_pin_bar`/`is_engulfing`/`body_size` —
   dùng chung cho cả xác nhận retest (bước 3, `breakout_retest._retest_confirmed`) lẫn
   scoring B1/B2/B3.
3. **Guard khoảng cách SL** (`main_loop.decide`) — sau khi tính `sl` cho tín hiệu BREAKOUT,
   nếu `signal.peak1 is not None` (scope: chỉ BRB, v1.2 fallback giữ hành vi cũ không
   guard) và `1R = |close[-1] − sl]`: `< min_stop_atr_mult×ATR14` → `wait/
   min_stop_distance`; `> max_sl_atr_mult×ATR14` → `wait/sl_too_wide`. Cạnh nhánh
   `lot_below_min` sẵn có, cùng pattern early-return.
4. **Gate scoring** (`main_loop.decide`) — tín hiệu BREAKOUT có `peak1` (BRB) và
   `scoring_enabled` mà tỉ lệ điểm < ngưỡng → outcome bị ghi đè thành `wait/
   scoring_below_threshold` TRƯỚC khi tới guard SL/lot. Nhánh "vetoed signal không đốt
   state" đã có sẵn cho v1.2 (`AWAITING_RETEST`) được tổng quát hoá theo pha: BRB vetoed
   tại `AWAITING_BREAKOUT2` giữ nguyên state (tăng `bars_waited`) trong ngân sách
   `breakout2_max_bars` còn lại, thay vì bị `evaluate()` reset về `NONE`.
5. **Persistence** (`engine/live_state.py`) — `breakout_state_to_dict/from_dict` serialize
   thêm `peak1/retest_low/retest_high`. `STATE_VERSION` bump 1→2 (payload shape đổi): một
   live run cũ resume sau restart sẽ gặp version không khớp → coi như "không có state"
   (fail-closed, đã là hành vi thiết kế sẵn của module) thay vì bị hiểu sai. Bảng
   `breakout_state` (SQL, `001_init.sql`) không có caller nào đọc/ghi (backtest giữ state
   trong memory, `SymbolContext.breakout_state`) nên **không cần migration** — đúng gợi ý
   của plan.
6. **Config** (`config/models.py` + `default.yaml`) — `BreakoutConfig` thêm
   `require_second_breakout`, `peak_max_bars=10`, `peak_min_atr_mult=1.0`,
   `retest_confirm_max_bars=15`, `breakout2_max_bars=10`, `require_retest_confirmation`,
   `sl_buffer_atr_mult=0.3` (BRB dùng; v1.2 fallback giữ `0.5` cũ qua default param của
   `compute_sl`), `min_stop_atr_mult=0.5`, `max_sl_atr_mult=2.0`, `scoring_enabled`,
   `scoring_threshold_ratio=0.66`.

### Tần suất lệnh giảm — đúng chủ trương, xử lý bằng cách tách test fixture thay vì nới tham số

BRB vào lệnh muộn hơn (phải đợi đủ Peak1 → retest xác nhận → breakout-2) và thêm gate
scoring, nên **tần suất lệnh giảm rõ rệt trên các fixture cố định sẵn có** — đúng rủi ro
plan đã lường trước ("chuẩn bị nới `scoring_threshold_ratio`/`peak_min_atr_mult` nếu đói
lệnh"). Kiểm tra thực tế trên fixture VN 600-bar D1: 0 lệnh khớp trong khi trước đó test đã
kỳ vọng ≥1 lệnh CLOSED; trên seed=42 mặc định của `test_replay_golden_with_costs`/
`test_live_runner`/API alert-plumbing test: tương tự.

Quyết định (thay vì tinh chỉnh tham số BRB để ép fixture ra đủ lệnh — việc đó là calibration
ngoài phạm vi plan này): các test **không kiểm chứng bản thân chiến lược BRB** (T+2.5, đáo
hạn VN30F, cash không short, cost model, live-runner restart/alert plumbing, on-demand
snapshot) chuyển sang chạy với `require_second_breakout=false` (qua override config trực
tiếp trong test, hoặc `PATCH /api/config` cho test API) — giữ nguyên fixture/seed đã có,
khôi phục đúng tần suất lệnh cũ cho các mục đích kiểm thử đó. BRB tự nó (máy trạng thái 4
pha, các nhánh reset theo từng pha, guard SL, ma trận điểm số, gate-không-đốt-state) được
kiểm bằng fixture dựng tay riêng trong `tests/unit/test_strategies.py` /
`tests/unit/test_scoring.py` / `tests/unit/test_main_loop.py`. Golden hash không bị đụng
tới (các test đổi đều tự so hai lần chạy hoặc so sánh tương đối, không ghim hằng số).

### Kiểm chứng

- `tests/unit/test_strategies.py`: chu trình BRB đầy đủ (breakout→Peak1→retest xác
  nhận→breakout-2 phát signal mang `peak1/retest_low/retest_high/retest_bars_ago`); 3
  nhánh reset (Peak1 không đạt trong `peak_max_bars`, retest quá hạn
  `retest_confirm_max_bars`, breakout-2 quá hạn `breakout2_max_bars`); fallback
  `require_second_breakout=false` tái tạo đúng hành vi v1.2 (signal không mang `peak1`).
- `tests/unit/test_scoring.py`: từng tiêu chí A1/A2/A4/B1/B2/B3/C1 pass/fail độc lập; A3
  bị loại khỏi `max_available` khi volume filter tắt (FOREX) và được cộng khi bật (VN);
  `ratio = total/max_available`.
- `tests/unit/test_main_loop.py`: guard `min_stop_distance`/`sl_too_wide` (dựng
  `AWAITING_BREAKOUT2` state tay + `base_ctx` warmed-up); gate `scoring_below_threshold`
  giữ nguyên `AWAITING_BREAKOUT2` (không đốt state, `bars_waited` tăng đúng 1); setup hợp
  lệ (trong guard, scoring tắt) vẫn ra `done`.
- Toàn bộ suite hiện có (trừ `-m slow`) xanh sau khi disable BRB cho các test không liên
  quan như trên: `tests/unit/test_stock_vn_decisions.py`,
  `tests/integration/test_replay_golden_stock_vn.py`,
  `tests/integration/test_replay_golden_with_costs.py`, `tests/unit/test_live_runner*.py`,
  `tests/api/test_alerts.py`, `tests/api/test_trade_snapshot.py`.

### Kết quả `replay --seed 42 --bars 5000` (verification, 2026-07-26)

`python -m bot.cli replay --seed 42 --bars 5000` với BRB mặc định (`require_second_breakout
=true`) ra **0 lệnh** trên seed 42 (`decision_stream_hash=
8836f7a1fc829355162e0ae8cce07f5f1d8f0b756f3955870a29ba2799ffdd9b`, ổn định 2 lần chạy — bất
biến #1 giữ nguyên). Cùng seed/cấu hình chạy `require_second_breakout=false` (v1.2) ra 21
lệnh. Truy vết: chỉ 10/5000 bar hoàn tất trọn chu trình 4 pha tới bar breakout-2 (phần lớn
`no_signal/breakout` là chưa arm được, không phải bị chặn) và cả 10 đều rớt
`scoring_below_threshold`; tắt hẳn scoring (guard SL vẫn bật) chỉ nâng lên **1 lệnh**. Vậy
điểm siết chính là chính máy trạng thái BRB (`peak_min_atr_mult=1.0`, xác nhận retest bắt
buộc, 3 ngân sách nến nối tiếp `peak_max_bars`+`retest_confirm_max_bars`+
`breakout2_max_bars`), không phải scoring hay guard SL.

Đây đúng như rủi ro plan đã lường trước ("tần suất lệnh giảm... chuẩn bị nới
`scoring_threshold_ratio`/`peak_min_atr_mult` nếu đói lệnh") — nhưng 0-1 lệnh/5000 bar trên
dữ liệu synthetic (random-walk, không có xung lực thật) là mức cực đoan, không đại diện cho
dữ liệu thị trường thật (xung lực Peak1 ≥1×ATR xảy ra tự nhiên hơn nhiều trên trend thật).
**Không tinh chỉnh tham số trong plan này** — việc đó là calibration cần dữ liệu thật, ngoài
phạm vi "triển khai đúng kế hoạch". Khuyến nghị bắt buộc trước khi chạy live: chạy lại
`replay`/backtest trên dữ liệu THẬT (không phải synthetic) của từng symbol, so histogram
`reason/stage` và số lệnh; nếu đói lệnh, nới theo đúng thứ tự plan gợi ý
(`scoring_threshold_ratio` trước, rồi `peak_min_atr_mult`) qua Config UI — không cần sửa
code, hai tham số này đã có trong `BreakoutConfig`/`default.yaml`.

### Sửa 4 lỗi ghép nối của BRB (2026-07-26, sau khi user báo backtest 1 năm 0 lệnh)

Kết luận "điểm siết chính là chính máy trạng thái BRB" ở mục trên **chưa đúng hoàn toàn**:
truy vết đó bị hai điểm mù (filter `wick` chặn dưới nhãn `no_signal/wick` lẫn với
`no_signal/breakout`; setup chết vì `sl_too_wide` sau khi đã đốt xong ngân sách bar). Rà lại
toàn chuỗi tìm ra 4 lỗi thật — đều **đổi hành vi mặc định**, đã sửa:

1. **Filter `wick` đọc sai nến.** `wick.py` đọc `iloc[-1]` = nến quyết định. Ở v1.2 nến đó
   *là* nến retest nên đúng; ở BRB nó là nến **breakout-2**, nên filter đi đòi bóng từ chối
   ≥ `min_ratio` trên đúng cái nến mà BRB (và scoring A1/A2) muốn là nến xung lực thân lớn
   bóng nhỏ — tức là chặn hệ thống mọi tín hiệu BRB. Nay định vị nến retest qua
   `signal.retest_bars_ago` (cùng cách scoring B1/B3 làm), `values` mang thêm
   `retest_bars_ago` để đọc được trên UI. v1.2 fallback không đổi (`retest_bars_ago=None`
   → offset 0 → vẫn `[-1]`).
2. **Thiếu invalidation "retest thủng sâu"** (spec_v2 §2 bước 3). `_evaluate_brb_pending`
   chỉ kiểm `low <= level + tolerance`, **không có biên dưới** → giá sập xuyên qua range vẫn
   tính là "đã retest", máy trạng thái tiến sang `AWAITING_BREAKOUT2` với `retest_low` rất
   thấp ⇒ SL neo ở đó luôn rớt `sl_too_wide`, đồng thời giam state thêm trọn
   `breakout2_max_bars`. Nhánh v1.2 vốn có `close > level` nên miễn nhiễm; BRB đánh rơi.
   Thêm `breakout.retest_max_depth_atr_mult` (mặc định `1.0`) — vượt độ sâu đó thì **huỷ
   setup** thay vì tiến pha. Tham số này cũng chính là thứ chặn trên `retest_low`, tức chặn
   trên 1R.
3. **Scoring A4 đo sai mốc.** `depth_pct` tính từ `peak1`, nhưng nến breakout-2 **theo định
   nghĩa** vừa mới vượt `peak1` ⇒ depth ≈ 0 ⇒ A4 gần như **không bao giờ** ghi điểm (mất
   cứng 1 điểm trên thang 10 của FOREX). spec §5 A4 đo từ **Range**. Đã đổi sang
   `range_high`/`range_low` theo hướng lệnh. Đo được sau khi sửa: A4 đạt 12/23 candidate
   (trước: 0/23).
   Kèm theo: **B1 thêm điều kiện "thân gần mép"** của spec (`is_pin_bar(body_max_position=)`,
   mặc định `None` nên mọi caller cũ không đổi) — trước đó B1 (bóng >2×thân) là phát biểu
   lồng của B3 (>1.5×thân), một tín hiệu tính điểm hai lần; nay B1 là tiêu chí thật sự mạnh
   hơn. Và bỏ nhánh chết trong `_retest_confirmed` (gọi `is_pin_bar` 2.0 rồi 1.5 — cái sau
   bao cái trước, ngưỡng thực tế luôn là 1.5).
4. **`min_stop_atr_mult`/`max_sl_atr_mult` không bao gói được 1R của BRB.** 1R có **sàn cấu
   trúc** = `peak_min_atr_mult + sl_buffer_atr_mult` ≈ 1.3×ATR (entry trên Peak1, SL dưới
   đáy retest). Nên `min_stop=0.5` là guard **chết** (không bao giờ kích từ dưới), còn
   `max_sl=2.0` chỉ để lại 0.7×ATR cho *(peak vượt hơn 1 ATR)* + *(độ sâu bóng nến retest)*
   — mà `require_retest_confirmation=true` lại **bắt buộc** bóng dài, tức setup càng đúng
   spec càng dễ chết. Đổi mặc định: `min_stop_atr_mult 0.5→1.0`, `max_sl_atr_mult 2.0→3.0`.
   Đây là **sai lệch có chủ đích khỏi spec_v2 §4** ("SL cap 2.0×ATR"): cap 2.0 của spec
   không tương thích với chính yêu cầu Peak1 ≥1×ATR của spec.

**Kiểm chứng** (`--seed 42 --bars 5000`, synthetic):

| | Trước | Sau |
|---|---|---|
| Bar tới được gate scoring | 10 | **23** |
| `wait/sl_too_wide` + `wait/min_stop_distance` | có (giam state) | **0** |
| Lệnh khi `scoring_enabled=false` | 1 | **3** |
| Lệnh khi scoring ON (ratio 0.66) | 0 | 0 |

Phân phối điểm của 23 candidate: `2/10 ×2, 3/10 ×7, 4/10 ×2, 5/10 ×6, 6/10 ×6` — **trần thực
tế là 6/10 = 0.60**, nên ngưỡng `0.66` cho 0 lệnh; hạ `0.60` sẽ cho 6 candidate qua. Tỉ lệ đạt
từng tiêu chí: `C1_rsi 23/23`, `B3_long_wick 23/23`, `A2_wick 17/23`, `A4_depth 12/23`,
`B1_pin_bar 9/23`, **`A1_body 3/23`**, **`B2_engulfing 0/23`** — A1 (thân > 2×SMA10) và B2
(engulfing) là hai tiêu chí gần như không đạt trên random-walk synthetic, đúng bản chất dữ
liệu chứ không phải lỗi.

**Vẫn KHÔNG tinh chỉnh `scoring_threshold_ratio` ở đây** — giữ nguyên lập luận của mục trên
(calibration cần dữ liệu thật). Hai việc follow-up lộ ra ở đây **đã làm ở mục kế tiếp**.

Determinism (bất biến #1) giữ nguyên: `--seed 42 --bars 2000` chạy 2 lần cho cùng
`decision_stream_hash=b97c2fb0386d62aa902e36ec3899d267c1acf776500f4dac64464a2274f80a5a`.
Stream/equity đổi so với trước là **CHỦ ĐÍCH** (4 sửa trên đều đổi hành vi); golden test chỉ
so hai lần chạy nên không cần re-pin. Test mới: `test_wick_reads_the_retest_bar_not_the_
breakout2_bar` (`test_filters.py`), `test_brb_resets_when_the_retest_breaks_deep_through_the_
level` + control `test_brb_shallow_retest_dip_is_still_accepted` (`test_strategies.py`),
`test_a4_depth_*` viết lại theo mốc Range + `test_a4_depth_uses_range_low_for_sell` +
`test_b1_pin_bar_fails_when_body_sits_mid_range` (`test_scoring.py`).

### Đưa ngưỡng scoring và tham số Range về đúng spec_v2 (2026-07-26)

Hai follow-up của mục trên, làm nốt.

**1. Tầng ngưỡng giữa của §5** (`strategies/scoring.py`, MỚI hàm `gate`). Trước đây chỉ có
một ngưỡng phẳng (`ratio < scoring_threshold_ratio` → chặn), bỏ mất tầng giữa của spec:
`≥8/12` vào lệnh · `6-7/12` **xem xét thêm nếu `A1+B1+C1 ≥ 5`** · `<6/12` huỷ. Triển khai:

- `ScoringResult.core_total` = điểm đạt trong riêng A1/B1/C1. `A1(2)+B1(2)+C1(1) = 5` đúng
  bằng ngưỡng spec, nên điều kiện thực chất là **cả ba đều đạt** — ghi rõ trong code để
  không ai đọc "≥5" thành một phép cộng lỏng.
- `core_required` để **tuyệt đối, không quy về ratio**: A1/B1/C1 không bao giờ chứa volume
  (A3) nên tổng đã so được giữa FOREX (max 10) và VN (max 12); quy ratio ở đây sẽ vô cớ
  làm ngưỡng khác nhau giữa hai lớp tài sản.
- `breakout.scoring_secondary_threshold_ratio` (mặc định `0.5` = 6/12, đúng biên dưới của
  dải giữa). Dưới biên này **không có đường cứu** — spec ghi "`<6/12` → ❌ hủy" vô điều kiện.
- Logic ngưỡng nằm trong `scoring.gate` (thuần, có test riêng) chứ không nhúng vào
  `main_loop`; `main_loop` chỉ gọi và ghi `core_total` vào `detail` của decision row.

**2. `range_period` 20→30 và `range_width.atr_mult` 1.5→2.5** (spec_v2 §3). Hai số này là
tàn dư của D2/D3 thời spec v1.2 — v1.2 **không** cho số nào cho độ rộng range nên D3 tự chọn
1.5; v2 §3 cho số tường minh (30 nến M15/H1, width > 2.5×ATR14) nên **v2 thắng**. Kèm theo:

- **VN profile (D1) đặt `range_period: 15`** (`config/profiles.py`). Bảng §3 chỉ có M15/H1
  (30) và H4 (12-15), **không có dòng D1** — lấy biên trên của dòng khung-cao là một **suy
  luận**, ghi ở đây để không ai coi là số của spec. Nếu không đặt, profile VN sẽ thừa hưởng
  30 bar ngày ≈ 6 tuần range, gần như chắc chắn bóp chết tần suất lệnh VN.
- `_consolidation_rows()` trong `test_strategies.py` nâng `n` 25→35: fixture BRB phải dài hơn
  `range_period` để cả cửa sổ range là vùng tích luỹ (25 bar < 30 làm mọi test BRB không arm
  được).

**Kiểm chứng — cả hai thay đổi gần như KHÔNG đổi gì trên synthetic, và đó là kết quả trung
thực chứ không phải chưa có hiệu lực:**

- Tầng giữa không giải cứu candidate nào: `core_total` phân phối `{1: 11, 3: 12}` trên 23
  candidate — **chưa bao giờ đạt 5**. A1 đạt 3/23 và không lần nào trùng với B1, nên
  `A1+B1+C1 = 5` không xảy ra. Đúng bản chất random-walk (A1 = thân > 2×SMA10 body).
- §3: số lần ARM 102→100, retest xác nhận 11→10 trên 5000 bar (đo bằng cách spy phase
  transition). `decision_stream_hash` **không đổi** — không phải vì thay đổi vô hiệu, mà vì
  hash chỉ phủ tuple `(bar_ts, symbol, reason, stage)`: một lần arm thêm/bớt mà không sinh
  signal vẫn ghi đúng `no_signal/breakout`. `filter_block_counts` (không nằm trong hash) đổi
  rõ: `range_width` 83→13 khi `range_period` 20→30 (cửa sổ rộng hơn ⇒ range rộng hơn ⇒ qua
  ngưỡng 2.5×ATR dễ hơn).
- Lệnh trên seed 42 vẫn **0** (scoring ON) / **3** (scoring OFF), y như sau 4 sửa trước.

Kết luận vẫn như cũ và giờ có số để chống lưng: **điểm siết còn lại là ngưỡng scoring trên dữ
liệu synthetic, không phải lỗi code.** Calibration đã được đưa thành trục sweep ưu tiên của
`plans/11-optimization.md` (❓1, cập nhật 2026-07-26) kèm hai ràng buộc: không sweep trên
synthetic, và số-trade-tối-thiểu là điều kiện sống-chết chứ không phải phụ.

Test mới (`test_scoring.py`): `test_core_total_counts_only_a1_b1_c1`,
`test_gate_primary_tier_passes_on_score_alone`,
`test_gate_middle_tier_passes_only_with_all_core_criteria`,
`test_gate_below_secondary_is_never_rescued`. Sửa
`test_brb_scoring_gate_blocks_and_does_not_burn_state` (`test_main_loop.py`) đặt **cả hai**
ngưỡng thành 1.1 — trước đó chỉ đặt ngưỡng chính, nên khi có tầng giữa nó có thể âm thầm
thôi kiểm tra đúng thứ nó mang tên.
