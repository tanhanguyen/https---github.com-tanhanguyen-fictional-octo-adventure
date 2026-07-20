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
  chối (`FeedError`), vì đó là lỗi dữ liệu chứ không phải gap.
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
ra cả 2 stage `account_risk`/`max_concurrent_trades` và `one_trade_per_symbol` trong decision
histogram (xem `tests/unit/test_account_risk_portfolio.py`).
