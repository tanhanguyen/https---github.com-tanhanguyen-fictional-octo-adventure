# Trading Bot Đa Chiến Lược (Breakout-Retest + Mean Reversion)

Bot giao dịch tự chuyển chiến lược theo chế độ thị trường (regime), chạy **end-to-end trên dữ liệu mock** (chưa kết nối sàn thật — đây là Phase 1). Backend Python + FastAPI, frontend React + Vite. Spec gốc: [`docs/spec_v1_2.md`](docs/spec_v1_2.md); mọi quyết định thiết kế & sai lệch có chủ đích: [`docs/decisions.md`](docs/decisions.md).

- **Chiến lược 1 — Breakout-Retest:** thị trường trend (ADX > 30 & ER > 0.6)
- **Chiến lược 2 — Mean Reversion:** thị trường range (ADX < 25 & ER < 0.3)
- **14 bộ lọc nền + 2 phụ trợ**, tất cả bật/tắt được qua UI, versioned trong DB
- **Decision log:** mỗi vòng `main_loop` giải thích được vì sao vào / không vào lệnh

Trạng thái: **Phase 1–5 đã xong** (core + test, main_loop + mock feed, REST API, React dashboard).

---

## 1. Yêu cầu

| | Phiên bản |
|---|---|
| Python | 3.10 (repo dùng pyenv `3.10.4`, venv sẵn ở `backend/.venv`) |
| Node.js | ≥ 18 (cho Vite) |

## 2. Cài đặt

**Backend** — venv đã tạo sẵn kèm dependencies. Nếu làm lại từ đầu:

```bash
cd backend
python3.10 -m venv .venv
./.venv/bin/pip install -e ".[dev]"      # hoặc cài trực tiếp: fastapi uvicorn "pydantic>=2" pandas numpy pyyaml pytest pytest-cov hypothesis httpx
```

**Frontend:**

```bash
cd frontend
npm install
```

---

## 3. Dùng như thế nào (3 cách)

### Cách A — CLI replay (nhanh nhất để kiểm engine)

Chạy toàn bộ bot qua dữ liệu synthetic, in tóm tắt. **Deterministic**: cùng seed → cùng hash decision stream.

```bash
cd backend
./.venv/bin/python -m bot.cli replay --seed 42 --bars 5000
```

In ra: số lệnh mỗi chiến lược, histogram lý do (`wait` / `no_signal` / `off` / `max_concurrent_trades_reached` / `done` …), histogram kết quả (WIN/LOSS), equity cuối, và `decision_stream_hash`. Chạy lần hai cùng seed phải ra **hash giống hệt**.

Chạy trên dữ liệu thật thay vì synthetic: import CSV một lần (idempotent theo nội dung file),
rồi replay bằng `--dataset` thay cho `--seed/--bars`:

```bash
./.venv/bin/python -m bot.cli import-csv --path data/csv/eurusd_15m.csv --symbol EURUSD --native-tf 15m
./.venv/bin/python -m bot.cli replay --dataset <dataset_id in ra ở trên>
```

`--native-tf` là khung gốc của file CSV (`15m|1H|4H|1D` — VD phái sinh VN thường chỉ có H4/D1,
không có 15m). Ràng buộc: `native_tf` phải mịn hơn hoặc bằng `config.timeframe` đang active,
sai thì lệnh báo lỗi rõ ràng thay vì chạy ra kết quả rác.

Nếu file gốc không đúng chuẩn `open_ts,open,high,low,close,volume`, dùng `scripts/convert_csv.py`
để chuyển đổi trước (Binance klines export, MetaTrader/Dukascopy tab-CSV không header, hoặc
JSON dạng TradingView/vnstock `{t,o,h,l,c,v}`):

```bash
./.venv/bin/python -m scripts.convert_csv binance --glob "data/examples/crypto/BTCUSDT-1h-*.csv" --out data/csv/BTCUSDT_1h.csv
./.venv/bin/python -m scripts.convert_csv mt --path "data/examples/forex/EURUSD15.csv" --out data/csv/EURUSD_real_15m.csv
./.venv/bin/python -m scripts.convert_csv vnstock --glob "data/examples/phai sinh vnstock/*VN30F1M*.json" --out data/csv/VN30F1M_1D.csv
```

### Cách A′ — Live paper trading (plan 07)

Chạy 24/7 trên dữ liệu **thật, thời gian thực** (Binance USDⓈ-M Futures klines — công khai,
không cần API key), khớp lệnh **giả lập** bằng chính order_engine. **Không đặt lệnh thật.**

```bash
cd backend
BOT_DB_PATH=data/live.db ./.venv/bin/python -m bot.cli live
```

- **Một process chạy cả danh mục** `config.symbols` — `MAX_CONCURRENT_TRADES`, daily-loss-limit
  và `max_total_open_risk_pct` là trần toàn tài khoản, mỗi symbol một process sẽ vô hiệu hoá
  chúng. `--symbol BTCUSDT` chỉ là override debug.
- `--testnet` đổi sang `testnet.binancefuture.com` (cùng schema, khác base URL).
- DB live **tách khỏi** DB backtest (mặc định `backend/data/live.db`, đổi bằng `BOT_DB_PATH`).
- Cảnh báo Telegram nếu đặt `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; không có thì log-only,
  mọi thứ vẫn chạy.
- Khởi động lại là an toàn: state máy trạng thái + lệnh đang mở được nạp lại từ DB, bar bị
  thiếu trong lúc chết được xử lý tuần tự (catch-up), bar đã xử lý không bao giờ chạy hai lần.
- Dừng: `POST /api/live/stop` (đặt cờ `run.stop_requested`, runner kiểm mỗi vòng lặp), hoặc Ctrl-C.
- Theo dõi: `GET /api/live/status` (lag, feed_state, uptime, equity) — dashboard hiện badge LIVE.

Feed live hiện có: **CRYPTO** qua Binance USDⓈ-M Futures, và **chứng khoán VN — cả spot
(`STOCK_VN_CASH`) lẫn phái sinh (`STOCK_VN_DERIV`)** qua **DNSE OpenAPI**
(`GET /price/ohlc`, docs: <https://developers.dnse.com.vn>). Chỉ FOREX còn chờ plan 10.

DNSE cần credentials trong môi trường — thiếu thì run live VN **từ chối khởi động**
(fail-closed), không chạy mù:

```bash
export DNSE_API_KEY=...
export DNSE_API_SECRET=...
```

Tải lịch sử OHLC về CSV chuẩn để backtest (cổ phiếu / phái sinh / chỉ số):

```bash
cd backend && ./.venv/bin/python -m scripts.fetch_dnse_ohlc --symbol VN30F1M --type DERIVATIVE --resolution 1D --from 2018-01-01 --out data/csv/VN30F1M_1D.csv
```

Hai điểm dễ sai đã được xử lý sẵn trong feed (chi tiết + danh sách "cần xác minh khi có
API key" ở `docs/decisions.md`, mục "Plan 07b"): giá **cổ phiếu** DNSE tính bằng **nghìn
VND** nên được nhân 1000 về VND nguyên, và nến **D1** được neo về **09:00 ICT** đúng quy
ước mọi dataset VN trong repo.

### Cách B — REST API (backend chạy độc lập)

```bash
cd backend
./.venv/bin/uvicorn bot.api.app:app --reload --port 8000
```

- Docs tương tác: <http://localhost:8000/docs>
- DB runtime lưu tại `backend/data/runtime.db` (SQLite, tự tạo)

Ví dụ vòng đời một phiên chạy:

```bash
curl localhost:8000/api/health
curl -X POST localhost:8000/api/run  -H 'content-type: application/json' -d '{"seed":42,"bars":5000}'   # tạo run
curl -X POST localhost:8000/api/run/step        # tiến 1 bar (step-synchronous, deterministic)
curl -X POST localhost:8000/api/run/play -H 'content-type: application/json' -d '{"interval_ms":200}'    # chạy liên tục (worker thread)
curl -X POST localhost:8000/api/run/pause
curl -X POST localhost:8000/api/run/reset

curl localhost:8000/api/account                 # equity, risk, open trades, daily_loss_count …
curl 'localhost:8000/api/decisions?limit=5'     # log quyết định gần nhất
curl localhost:8000/api/decisions/stats         # histogram "vì sao không có lệnh?"
```

**Bật/tắt filter & đổi symbol/timeframe/chiến lược** đều qua một cơ chế duy nhất — `PATCH /api/config` (deep-merge → validate → tạo config version mới + activate). Ví dụ tắt bộ lọc MTF:

```bash
curl -X PATCH localhost:8000/api/config -H 'content-type: application/json' \
     -d '{"filters":{"mtf":{"enabled":false}}}'
```

### Cách C — Dashboard đầy đủ (backend + frontend)

**Terminal 1** — backend:

```bash
cd backend && ./.venv/bin/uvicorn bot.api.app:app --reload --port 8000
```

**Terminal 2** — frontend (Vite proxy `/api` → `localhost:8000`):

```bash
cd frontend && npm run dev
```

Mở <http://localhost:5173>. Năm trang:

- **Dashboard** — AccountPanel, RiskGauge, RunControls (Step/Play/Pause/Reset), EquityChart, bảng lệnh đang mở
- **Config** — form filter render **hoàn toàn từ** `/api/config/schema` (thêm filter mới không cần sửa frontend); toggle từng filter + chỉnh params
- **Datasets** — quản lý dataset: tạo synthetic (seed/bars) hoặc import CSV thật
- **Decisions** — bảng log + chi tiết từng quyết định (đủ 16 dòng filter, tô đậm dòng đang chặn)
- **Trades** — lịch sử lệnh + trade events + liên kết ngược về decision

⚠️ Frontend gọi API qua Vite proxy (`/api` → `localhost:8000`). Nếu thấy **502 Bad Gateway**
(vd `GET /api/datasets`) nghĩa là backend ở Terminal 1 **chưa chạy hoặc đã crash** — proxy
không nối được cổng 8000. Kiểm tra log ở Terminal 1 và `curl localhost:8000/api/health` trước.

**Chạy backtest trên dữ liệu CSV thật từ dashboard:**

1. Đặt file CSV chuẩn (`open_ts,open,high,low,close,volume`, UTC) dưới `backend/data/csv/`
   (file chưa đúng chuẩn → convert bằng `scripts/convert_csv.py`, xem Cách A).
2. Trang **Datasets** → form *Import CSV thật*: nhập đường dẫn **server-side, tương đối với
   thư mục `backend/`** (vd `data/csv/eurusd_15m.csv` — không phải upload file từ máy),
   symbol (vd `EURUSD`) và Native TF đúng khung gốc của file (`15m|1H|4H|1D`).
   Import idempotent theo nội dung file: import lại cùng file → trả về cùng dataset, không tạo bản mới.
   Bảng Datasets hiển thị metadata: khoảng thời gian, số bar, số gap, sha256 (hover cột ID).
3. Trang **Dashboard** → *Điều khiển chạy bot* → dropdown **Dataset**: chọn dataset vừa import
   (chọn dataset thì Seed bị bỏ qua; để `(synthetic seed/bars)` nếu muốn chạy mock như cũ)
   → **New Run** → Step/Play như bình thường.
4. Ràng buộc: `native_tf` của dataset phải **mịn hơn hoặc bằng** `timeframe` đang active
   (đổi ở trang Config). VD dataset 1D không chạy được với `timeframe: 1H` — tạo run sẽ báo lỗi
   thay vì chạy ra kết quả rác.
5. DXY thật (tuỳ chọn): import CSV với symbol `DXY` như bước 2, rồi trỏ filter dxy vào nó qua
   Config (`filters.dxy.dataset_id` = id dataset DXY). Không có thì filter `dxy` dùng synthetic
   như cũ hoặc tắt đi.

---

## 4. Kiểm thử

```bash
cd backend
./.venv/bin/pytest -q            # unit + integration + api
./.venv/bin/mypy src             # strict, phải sạch
./.venv/bin/ruff check src       # lint
```

Test then chốt: `test_no_lookahead` (bất biến MTF nến-đã-đóng), `test_replay_golden` (hash seed=42 để refactor an toàn), `test_no_wallclock` (cấm `datetime.now` trong engine), `test_counters_consistent` (cache == derived).

---

## 5. Kiểm chứng nhanh (smoke)

1. `pytest -q` xanh.
2. `python -m bot.cli replay --seed 42 --bars 5000` → có lệnh cả 2 chiến lược, histogram reason phủ hết từ vựng §8, equity không nhảy bậc phi lý.
3. Chạy lại (2) → **hash giống hệt** (determinism).
4. Bật API + dashboard → Step vài lần, thấy equity/open trades/daily_loss_count đổi.
5. Tắt một filter (vd `mtf`) qua UI → tạo config version mới, các decision sau đó hiện `mtf` với `enabled=false, evaluated=false`.
6. A/B chứng minh filter có tác dụng: tắt `confirmation_lag`, chạy lại cùng seed → **số lệnh phải đổi**.
7. Chi phí giao dịch có tác dụng: chạy `replay --seed 42 --bars 600` với `execution.costs`
   mặc định (0) rồi lại với `execution.costs.spread_pips/slippage_pips/commission_per_lot > 0`
   (patch qua `PATCH /api/config` hoặc sửa `config/default.yaml` tạm) → **equity cuối cùng
   phải thấp hơn hoặc bằng** phiên bản không phí (`test_replay_golden_with_costs` pin sẵn).

---

## 6. Làm gì tiếp theo

### Việc nên làm ngay (củng cố Phase 1)
- **Chạy đủ verification §5** ở trên và đọc mắt equity curve + histogram lý do.
- **A/B từng filter** để xác nhận mỗi cái thực sự thay đổi hành vi (không phải toggle chết).
- Xem lại các **sai lệch có chủ đích** đã ghi ở [`docs/decisions.md`](docs/decisions.md) (D1–D11, 12 điểm lệch khỏi spec) — xác nhận còn đồng ý.

### Phase 2 — trước khi thêm profile chứng khoán VN (⚠️ cần chốt, xem chi tiết ở cuối `docs/decisions.md`)
§7 của spec viết cho **chứng khoán Mỹ**, không port thẳng sang VN được:

| Vấn đề | Áp cho | Cần chốt |
|---|---|---|
| Không bán khống | `STOCK_VN_CASH` | Chặn tín hiệu SELL + ghi log rõ (`ALLOW_SHORT=false`) |
| Đáo hạn hợp đồng (VN30F1M, thứ 5 tuần 3) | `STOCK_VN_DERIV` | Quy tắc nối chuỗi giá (back-adjust vs ratio-adjust) + lịch roll |
| Time Stop 8h vô nghĩa trên D1/W1 | Cả hai | Tắt `time_stop` hoặc cho `TIME_STOP_HOURS` theo loại tài sản |
| T+2.5 | `STOCK_VN_CASH` | Engine phải biết để không mô phỏng lệnh thoát trong ngày |
| Đơn vị & bước giá (lô 100 cp / nhân 100.000đ) | Cả hai | Hai `InstrumentSpec` riêng cho `calculate_lot` |

### Về sau (ngoài Phase 1)
- **Kết nối dữ liệu thật** — thay `data/synthetic` bằng CSV/broker feed (hạ tầng `csv_feed` đã có chỗ).
- **Phí giao dịch** — hiện `spread_pips: 0` để test tính tay khớp chính xác; §10 yêu cầu backtest có phí, bật khi chạy thật.
- **Nguồn tin tức** cho filter `news` (hiện `NEWS_BLACKLIST=[]`, off).
- **Đa symbol** — để `MAX_CONCURRENT_TRADES` (Forex=3, Stock VN=2) thực sự có nghĩa.

**Ràng buộc xuyên suốt:** không tự thêm chiến lược/bộ lọc ngoài spec — thiếu gì so với tài liệu thì hỏi lại trước khi quyết.

---

## 7. Cấu trúc

```
backend/src/bot/
├── core/         types, clock (inject được — engine cấm đồng hồ hệ thống), timeframes, wallclock
├── indicators/   EMA, ATR, ADX, RSI, Efficiency Ratio, Z-score … (hàm thuần pandas, đúng công thức §6)
├── filters/      16 filter (registry, bật/tắt độc lập)
├── strategies/   breakout_retest, mean_reversion
├── engine/       context, main_loop (evaluate-all-decide-after), order_engine, runner, decision_log
│              live_runner + live_state + live_factory (plan 07: paper trading thời gian thực)
├── data/         synthetic feed (mock), csv_feed, live_feed (Binance futures), resample, dataset
├── db/           SQLite schema + repositories (bộ đếm DERIVED, config versioned)
├── api/          FastAPI routers (mỏng) trên RunnerService
├── notify.py     cảnh báo Telegram (không token → log-only)
└── cli.py        `python -m bot.cli replay|live|ab|import-csv|import-news`

frontend/src/     React + Vite + TS — pages/ Dashboard, Config, Decisions, Trades
docs/             spec_v1_2.md (nguồn chân lý), decisions.md (C1–C11, D1–D11, sai lệch)
```

**Hướng phụ thuộc một chiều:** `indicators → filters/strategies → engine → api`. Ba tầng đầu thuần pandas, không I/O — test được không cần DB hay FastAPI.
