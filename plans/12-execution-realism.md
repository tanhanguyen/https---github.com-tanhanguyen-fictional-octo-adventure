# Plan 12 — (Nâng cao) Độ thật của khớp lệnh: funding fee, margin guard, websocket, hiệu chỉnh slippage

> Đọc trước: `plans/00-roadmap.md` (Bất biến), `plans/02-real-data.md`, `plans/07-live-paper.md`,
> `plans/08-broker-execution.md`. Bốn mục dưới đây **độc lập nhau** — làm lẻ từng mục được,
> theo thứ tự nào cũng được; mỗi mục tự đứng như một việc giao cho Sonnet.
> Đây là các deviation "chấp nhận có ghi chép" của plan 07/08 — plan này xoá dần chúng khi cần.
> **NGOẠI LỆ (user chốt 2026-07-18, đợt 3): với CRYPTO FUTURES, 12b KHÔNG còn là tuỳ chọn —
> là prerequisite bắt buộc trước khi plan 08 arm mode `real`; 12a là prerequisite để tin
> kết quả paper crypto khung H4/D1** (chi tiết ở đầu plan 08).

## 12a. Funding fee perpetual trong backtest/paper (crypto)

- Nguồn: `GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT` — lịch sử funding
  rate công khai, không cần key. Import thành dataset qua đúng đường CSV/sha256 của plan 02
  (cùng khuôn DXY): script `scripts/fetch_funding.py` tải + lưu CSV, engine chỉ đọc dataset —
  **không I/O trong engine** (Bất biến #6), dữ liệu nạp sẵn vào `Context`.
- Order_engine: tại các mốc funding (mỗi 8h — 00:00/08:00/16:00 UTC), trade OPEN trên symbol
  perpetual bị cộng/trừ `funding_rate × notional` vào PnL đang chạy (dấu theo hướng vị thế).
- Config: `execution.costs.funding_enabled` (default **false** — golden hash không đổi);
  bật lên cho run crypto → hash mới theo nghi thức re-pin Bất biến #1. Chỉ áp dụng khi
  symbol được đánh dấu perpetual trong profile (plan 04) — forex/VN không dính.
- ❓ Live paper (plan 07): mốc funding rơi giữa hai bar close — đề xuất đơn giản: settle tại
  bar close ĐẦU TIÊN sau mốc funding, dùng rate của mốc đó (sai số vài phút, ghi decisions.md).
- Test: dựng tay 1 trade Long qua 2 mốc funding (rate dương rồi âm) → PnL khớp tính tay;
  `funding_enabled=false` → mọi test cũ nguyên vẹn.

## 12b. Margin/liquidation guard (crypto futures — BẮT BUỘC trước khi plan 08 arm real)

- Vấn đề: bot sizing theo `MAX_RISK_PER_TRADE` khoảng-cách-tới-SL, không biết gì về margin.
  Với leverage thấp (3–5x, ❓ plan 08) giá liquidation thường xa hơn SL nhiều — nhưng phải
  **kiểm chứ không giả định**.
- Guard (thuộc nhóm hard-caps của plan 08, kiểm ngay trước `place_market`): ước lượng giá
  liquidation ISOLATED ≈ hàm(entry, leverage, maintenance margin rate từ
  `GET /fapi/v1/leverageBracket`) — công thức Sonnet xác minh với docs Binance khi làm.
  Nếu liquidation nằm GẦN hơn SL (bị chạm trước SL) → không vào lệnh, decision
  `reason = wait`, `stage = margin_guard` (từ vựng §8 giữ nguyên — Bất biến #4), cảnh báo
  Telegram kèm leverage cần thiết để hợp lệ.
- Backtest KHÔNG mô phỏng liquidation (để nguyên deviation) — guard này là phanh an toàn
  phía live/real, không phải mô hình. Ghi rõ ranh giới đó vào decisions.md.
- Test: mock leverageBracket, case liquidation-gần-hơn-SL bị chặn đúng reason/stage,
  case bình thường đi qua.

## 12c. Websocket feed (nâng cấp tùy chọn của plan 07)

- ❓ Có đáng làm không: với bar 15m, polling mỗi phút đã đủ và ít trạng thái lỗi hơn —
  **chỉ làm khi user thấy độ trễ ~1 phút là vấn đề**. Nếu không chốt, bỏ qua mục này.
- Nếu làm: Binance `wss://fstream.binance.com/ws/btcusdt@kline_15m`, chỉ xử lý message có
  `k.x == true` (bar đã đóng) → đẩy vào cùng interface LiveFeed; **polling giữ làm fallback**
  (websocket rớt → quay về poll, cảnh báo, không crash). LiveRunner không đổi —
  bar đến sớm hơn vài chục giây, đường xử lý y hệt (idempotent theo bar_ts đã có sẵn).
- Test: fake websocket bơm kịch bản (bar chưa đóng bị bỏ, rớt kết nối → fallback polling);
  test then chốt live ≡ replay của plan 07 phải giữ nguyên.

## 12d. Hiệu chỉnh slippage/phí từ số liệu thật (khép vòng plan 08 → plan 02)

- Nguồn: các cặp `fill_price_broker` vs `fill_price_model` + phí thật mà plan 08 đã ghi
  trong thời gian chạy demo/real.
- `scripts/calibrate_costs.py`: đọc DB live → phân bố slippage (theo symbol, theo giờ),
  phí trung bình thực tế → in đề xuất giá trị mới cho `execution.costs.*` của backtest
  (slippage_pips, commission…). **Chỉ đề xuất, không tự ghi config** — user xem báo cáo
  rồi tự PATCH config (giữ nguyên tắc versioned-config, và đây là quyết định mô hình).
- Report: thêm mục "costs thực nghiệm vs costs backtest" vào trang Report (plan 03);
  chạy lại backtest với costs mới → so metric trước/sau một cách trung thực.
- ❓ Ngưỡng dữ liệu tối thiểu trước khi tin số liệu — đề xuất ≥ 30 fill/symbol.
- Test: script trên DB dựng tay ra đúng phân bố; không mạng.

## Definition of done

- Mỗi mục làm xong tự khép: test/mypy/ruff xanh, decisions.md có mục tương ứng,
  golden hash chỉ đổi ở mục 12a khi bật funding (đúng nghi thức re-pin).
- Không mục nào đổi semantics quyết định của engine ngoài điểm đã nêu (12a thêm dòng chi phí,
  12b thêm một guard trước lệnh thật).
