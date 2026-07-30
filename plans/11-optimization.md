# Plan 11 — (Nâng cao) Sweep tham số + walk-forward, báo cáo overfit

> Đọc trước: `plans/00-roadmap.md` (Bất biến), `plans/03-backtest-analytics.md`.
> Phụ thuộc: plan 02 (dữ liệu thật + chi phí), plan 03 (metrics + run registry).
> Đây là phần "nghiên cứu" đã bị plan 03 loại khỏi phạm vi — làm khi user muốn *tìm*
> tham số tốt hơn chứ không chỉ *đo* chiến lược.

## Ràng buộc cứng (không thương lượng)

- **Không thêm chiến lược/bộ lọc mới** — ràng buộc xuyên suốt của repo. Sweep CHỈ quét
  các tham số **đã tồn tại trong config** (ngưỡng, hệ số, toggle của 16 filter + 2 chiến
  lược hiện có). Muốn quét một tham số chưa configurable → phải hỏi user trước khi thêm.
- Mỗi run trong sweep là một run bình thường qua Runner hiện tại: config version riêng,
  deterministic (seed cố định), ghi vào run registry của plan 03. Sweep không có đường
  tắt nào bỏ qua engine.
- `test_replay_golden` không liên quan gì tới sweep (sweep không đổi hành vi engine);
  nếu plan này buộc phải đổi engine ở đâu đó → theo đúng nghi thức re-pin của Bất biến #1.

## Quyết định user phải chốt

1. ❓ **Danh sách tham số được quét + khoảng giá trị** — đề xuất đợt đầu giữ hẹp:
   `confirmation_lag`, `retest_tolerance` (hệ số ATR, D5), `sl_scale`, các toggle filter
   (bật/tắt từng cái — nối tiếp A/B harness của plan 01). Ngưỡng regime (ADX 30/25, ER 0.6/0.3)
   là số của spec — quét chúng tức là rời spec, cần user gật riêng.

   **Cập nhật 2026-07-26 (sau BRB v2, plan 15) — đây giờ là trục ƯU TIÊN của plan này.**
   BRB để lại một việc calibration cụ thể mà `docs/decisions.md` cố ý không làm trong plan
   15 ("cần dữ liệu thật, ngoài phạm vi triển khai đúng kế hoạch"). Trục quét, theo đúng thứ
   tự nới đã ghi trong decisions.md:
   `strategies.breakout.scoring_threshold_ratio` (0.50 / 0.55 / 0.60 / 0.66) →
   `peak_min_atr_mult` (0.7 / 1.0 / 1.3) → `retest_max_depth_atr_mult` (0.5 / 1.0 / 1.5) →
   `max_sl_atr_mult` (2.5 / 3.0 / 3.5). Cả 4 **đã configurable**, không cần thêm field —
   đúng ràng buộc "sweep chỉ quét tham số đã tồn tại" ở trên.
   Hai lưu ý bắt buộc khi chạy:
   (a) **Không sweep trên dữ liệu synthetic.** Đã đo trên `--seed 42 --bars 5000`: A1 (thân
   nến > 2×SMA10) đạt 3/23 candidate và B2 (engulfing) đạt 0/23, nên trần điểm thực tế chỉ
   6/10 và mọi ngưỡng ≥0.66 cho 0 lệnh — random-walk không sinh xung lực thật, sweep ở đó
   chỉ đo đặc tính của bộ sinh số ngẫu nhiên.
   (b) **Số trade tối thiểu N của ❓2 là ràng buộc sống-chết ở đây**, không phải điều kiện
   phụ: vùng tham số BRB có cả một mảng cho 0–3 lệnh/5000 bar, mà PF của 2 lệnh thì vô nghĩa.
2. ❓ Metric chọn tham số trên IS — đề xuất: **profit factor** với ràng buộc
   `max_drawdown ≤ X%` và số trade tối thiểu N (metric đơn lẻ dễ bị gãy; PF + ràng buộc
   là thoả hiệp đơn giản). X, N user chốt.
3. ❓ Kích thước cửa sổ walk-forward — đề xuất IS 12 tháng / OOS 3 tháng, trượt 3 tháng
   (phụ thuộc độ dài dữ liệu thật có được từ plan 02; dữ liệu ngắn hơn thì co lại theo tỷ lệ 4:1).

## Thiết kế

### 1. `bot/research/sweep.py` — chạy lưới tham số

- Input: file YAML mô tả sweep — dataset, khoảng thời gian, và các trục tham số
  (grid; thêm `mode: random` + `n_samples` khi lưới quá lớn). Ví dụ:
  `confirmation_lag: [1, 2, 3]` × `sl_scale: [0.8, 1.0, 1.2]`.
- Với mỗi tổ hợp: tạo config version mới (qua đúng đường versioned-config hiện có) → chạy
  Runner → metrics (plan 03) → một dòng kết quả. Kết quả sweep ghi bảng
  `sweep(sweep_id, params_json, run_id, metrics_json)` — mỗi dòng trỏ về run thật trong
  registry để drill-down được.
- Chạy tuần tự mặc định; `--workers N` dùng multiprocessing, mỗi worker một DB tạm
  (`BOT_DB_PATH` riêng) rồi merge dòng kết quả về DB chính — tránh tranh chấp write SQLite.
  Kết quả phải **giống hệt** chạy tuần tự (test).
- Guard chi phí: in số tổ hợp + ước lượng thời gian trước khi chạy; > ngưỡng (mặc định 200
  tổ hợp) thì đòi `--yes`.

### 2. `bot/research/walkforward.py` — walk-forward

- Chia chuỗi dữ liệu thành các cửa sổ (IS, OOS) liên tiếp theo ❓3. **Chống leak tuyệt đối**:
  OOS bắt đầu sau khi IS kết thúc; warmup indicator của OOS chỉ dùng bar ≤ điểm cắt
  (cùng tinh thần `test_no_lookahead`); có test biên cửa sổ riêng.
- Mỗi cửa sổ: sweep trên IS → chọn tổ hợp theo metric ❓2 → chạy đúng 1 lần trên OOS
  bằng tổ hợp đó. Kết quả cuối = chuỗi OOS nối lại (equity curve out-of-sample thuần).
- **Báo cáo overfit** (phần quan trọng nhất): per-window bảng `IS metric vs OOS metric`
  + tỷ lệ suy giảm (degradation); phân bố metric của TOÀN BỘ tổ hợp IS chứ không chỉ
  tổ hợp thắng (nếu tổ hợp thắng chỉ nhỉnh hơn median một sợi tóc → tín hiệu nhiễu);
  tổng số tổ hợp đã thử (mẫu số của selection bias). Không hứa hẹn gì hơn — các kỹ thuật
  thống kê sâu hơn (deflated Sharpe…) để ngoài phạm vi.

### 3. API + UI

- `GET /api/sweeps`, `GET /api/sweeps/{id}` (bảng kết quả + params). Trang **Sweep**:
  bảng sortable theo metric, click dòng → trang Report của run đó (plan 03 có sẵn);
  sweep đúng 2 trục tham số → thêm heatmap đơn giản. Walk-forward: bảng IS-vs-OOS
  per-window + equity curve OOS nối.
- CLI: `python -m bot.cli sweep --config sweeps/grid.yaml`,
  `python -m bot.cli walkforward --config sweeps/wf.yaml`.

## Kiểm thử

- Sweep trên dataset nhỏ cố định: đủ số dòng kết quả, mỗi run deterministic, kết quả
  `--workers 4` ≡ tuần tự.
- Walk-forward: test biên cửa sổ (bar OOS không lọt vào IS, warmup không nhìn qua điểm cắt);
  test chọn-tham-số ra đúng tổ hợp trên dữ liệu dựng tay.
- Không test nào cần dữ liệu thật — synthetic dataset là đủ.

## Definition of done

- Một sweep thật (tham số ❓1) + một walk-forward thật trên dữ liệu plan 02 chạy trọn vẹn;
  trang Sweep hiển thị được; báo cáo overfit đọc hiểu được (user nghiệm thu bằng mắt);
  test/mypy/ruff xanh; decisions.md ghi metric ❓2 + cửa sổ ❓3 đã chốt.
