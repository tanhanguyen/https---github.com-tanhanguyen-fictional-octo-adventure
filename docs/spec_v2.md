# TÀI LIỆU THIẾT KẾ BOT GIAO DỊCH - PHIÊN BẢN V2.0

**Chiến lược: Breakout → Retest → Breakout (BRB) với Ma trận Xác nhận & SL/TP Tối ưu**  
**Áp dụng cho: Forex, Crypto, Chứng khoán Việt Nam**
---

## MỤC LỤC

1. Tóm tắt thay đổi chiến lược
2. Chiến lược BRB - Quy trình 4 bước
3. Xác định vùng Range và tham số khung thời gian
4. SL/TP Tối ưu & Kiểm soát rủi ro vốn
5. Ma trận Xác nhận (Scoring Matrix)
6. Danh sách bộ lọc tích hợp
7. Tổng kết

---

## 1. TÓM TẮT THAY ĐỔI CHIẾN LƯỢC

| Yếu tố | Phiên bản cũ | Phiên bản mới (V2.0) |
|--------|--------------|----------------------|
| **Phương pháp** | Breakout → Retest → Entry ngay | **Breakout → Retest → Breakout (BRB)** |
| **Thời điểm vào lệnh** | Tại vùng Retest (sớm) | **Sau khi phá vỡ đỉnh Peak1** (muộn hơn) |
| **Mục tiêu** | R:R cao, Win Rate thấp | **Win Rate cao, R:R cân bằng** |
| **Bộ lọc chính** | Cơ bản (ADX, ATR) | **Ma trận điểm số (8 tiêu chí)** |
| **Win Rate kỳ vọng** | ~45-55% | **~65-75%** |
| **R:R hiệu quả** | 1:3 – 1:4 | **1:2 – 1:3** |

---

## 2. CHIẾN LƯỢC BRB - QUY TRÌNH 4 BƯỚC

**Bước 1: Xác định vùng Range và Breakout đầu tiên**
- Xác định `Range_High` và `Range_Low` theo khung thời gian đã chọn.
- Giá đóng cửa vượt qua `Range_High` (BUY) hoặc `Range_Low` (SELL).
- Bot chưa vào lệnh – chỉ đánh dấu và theo dõi.

**Bước 2: Xác định Peak1**
- `Peak1` = đỉnh cao nhất sau Breakout đầu tiên (trong 5-10 nến tiếp theo).
- Yêu cầu: Peak1 phải cách Range_High ít nhất `1.0 × ATR(14)`.
- Nếu không tạo được Peak1 rõ ràng → hủy tín hiệu.

**Bước 3: Chờ Retest**
- Giá quay lại chạm vùng Range_High (BUY) hoặc Range_Low (SELL), sai số `±0.3%`.
- Tại Retest phải có Pin Bar, Engulfing hoặc bóng dài xác nhận.
- Nếu Retest thủng sâu không quay lại → hủy tín hiệu.

**Bước 4: Breakout lần 2 (Vào lệnh)**
- Giá phá vỡ Peak1, vào lệnh theo thứ tự ưu tiên:
  - Nến phá vỡ đóng cửa trên Peak1 → Entry = giá đóng cửa.
  - Nến tiếp theo mở cửa không quá 0.2% xa Peak1 → Entry = giá mở cửa.
  - Hoặc đặt lệnh chờ tại `Peak1 + 2 pip` (Forex) hoặc `Peak1 * 1.0005` (Crypto/Stock).

**Giới hạn số nến**
- Bước 2: Xác định Peak1
  - Peak1 là đỉnh cao nhất trong vòng 10 nến ngay sau Breakout đầu tiên.
  - Giới hạn thời gian: Chỉ tính Peak1 trong 10 nến đầu tiên sau breakout. Nếu sau 10 nến mà giá vẫn chưa tạo được đỉnh rõ ràng (chỉ đi ngang hoặc tăng nhẹ) → hủy tín hiệu.
  - Yêu cầu: Peak1 phải cách Range_High ít nhất 1.0 × ATR(14). Nếu không đạt → hủy.

- Bước 3: Chờ Retest
  - Retest phải xảy ra trong vòng 15 nến kể từ khi Peak1 được hình thành. Quá 15 nến mà giá vẫn chưa quay lại chạm Range → hủy tín hiệu (vì sóng hồi quá lâu, mất đà).
  - Tại vùng Retest, giá phải chạm vào phạm vi ±0.3% của Range_High (BUY) hoặc Range_Low (SELL).
  - Nến Retest phải là Pin Bar, Engulfing hoặc có bóng dài xác nhận. Nếu không có dấu hiệu từ chối vùng giá này trong 3 nến tiếp theo → hủy.

- Bước 4: Breakout lần 2 (Vào lệnh)
  - Sau Retest, giá bật lên và phá vỡ Peak1. Breakout lần 2 này phải xảy ra trong vòng 10 nến kể từ khi kết thúc nến Retest. Nếu quá 10 nến mà giá vẫn chưa vượt Peak1 → hủy (có thể đã chuyển sang sideway).

Vào lệnh theo thứ tự ưu tiên:
Nến phá vỡ Peak1 đóng cửa trên Peak1 → Entry = giá đóng cửa (ngay tại nến đó).
Nếu nến phá vỡ có bóng trên dài (wick) vượt Peak1 nhưng đóng cửa dưới Peak1, thì chờ nến tiếp theo. Nếu nến tiếp theo mở cửa cách Peak1 không quá 0.2% → Entry = giá mở cửa.
Hoặc đặt lệnh chờ tại Peak1 + 2 pip (Forex) hoặc Peak1 * 1.0005 (Crypto/Stock) – lệnh chờ này có hiệu lực trong vòng 3 nến tiếp theo, nếu không khớp thì hủy.

---

## 3. XÁC ĐỊNH VÙNG RANGE VÀ THAM SỐ KHUNG THỜI GIAN

**Số nến Range theo khung thời gian:**
Xét dài ra để tránh fake breakout, và tránh tình trạng entry và SL chung 1 nến

| Khung | Số nến | Điều kiện đủ rộng |
|-------|--------|------------------|
| M15   | 30     | (Range_High - Range_Low) > 2.5 × ATR(14) |
| H1    | 30     | (Range_High - Range_Low) > 2.5 × ATR(14) |
| H4    | 12-15  | (Range_High - Range_Low) > 2.5 × ATR(14) |

**Công thức:**  
`Range_High = MAX(High, N)`  
`Range_Low = MIN(Low, N)`  
Nếu `Range_High - Range_Low < 2.5 × ATR(14)` → không giao dịch.

## 4. SL/TP TỐI ƯU & KIỂM SOÁT RỦI RO VỐN

**Stop Loss (SL) – tránh bị quét thanh khoản:**
- BUY: `SL = Đáy nến Retest - (0.3 × ATR(14))`
- SELL: `SL = Đỉnh nến Retest + (0.3 × ATR(14))`
- **Giới hạn SL tối đa:** không vượt quá `2.0 × ATR(14)`.

**Take Profit (TP) – chia làm 2 mục tiêu:**
- `Sóng1 = Peak1 - Đáy Retest`
- **TP1 (chốt 50%):** `Entry + (1.618 × Sóng1)`  
- **TP2 (thả nổi 50%):** Trailing Stop động theo đáy cấu trúc (nâng SL dưới mỗi đáy mới).

**Quản lý sau TP1:** kéo SL phần còn lại về Entry (hòa vốn). Giữ lệnh đến khi Trailing Stop chạm hoặc xu hướng đảo chiều.

**Định nghĩa Toán học cho "Đáy/Đỉnh Cấu trúc" (Trailing Stop):**
- Sử dụng cấu trúc Fractal (Khuyên dùng vì đúng bản chất Price Action)
  - Định nghĩa Fractal Low (Đáy cấu trúc lệnh BUY): Là mức giá Thấp nhất (Low) của 1 cụm 5 nến, trong đó: nến giữa có giá Low thấp nhất, 2 nến liền trước và 2 nến liền sau có giá Low cao hơn.
  - Logic Trailing: Khi giá tạo một Fractal Low mới cao hơn Fractal Low cũ, SL sẽ tự động dời lên mức Giá Low của Fractal mới - (0.2 * ATR).

**Kiểm soát rủi ro vốn:**  
- Rủi ro tối đa mỗi lệnh: **2% tài khoản**.
- Công thức kiểm tra: `(SL_distance / Entry) × 100 ≤ 2%`. Nếu lớn hơn → không vào lệnh, huỷ theo dõi, chờ setup chu trình breakout khác.

---

## 5. MA TRẬN XÁC NHẬN (SCORING MATRIX)

**Mục đích:** Đây là thêm thêthêm, không phải thay thế các config cũ. Thêm điều kiện lọc tín hiệu, chỉ vào lệnh khi đạt đủ điểm → giảm fake breakout, tăng Win Rate.

**Bảng tiêu chí và điểm số:**

| # | Tiêu chí | Điểm | Điều kiện đạt |
|---|----------|------|---------------|
| **A. BREAKOUT** |
| A1 | Thân nến breakout | 2 | Thân > 2 × SMA(Body, 10) |
| A2 | Bóng nến breakout | 1 | Bóng trên (BUY) hoặc bóng dưới (SELL) < 0.3 × Body |
| A3 | Khối lượng breakout | 2 | Volume > 1.8 × SMA(Volume, 20) *(nếu có)* |
| A4 | Breakout Depth | 1 | Đóng cửa cách Range ≥ 0.3% giá |
| **B. RETEST** |
| B1 | Pin Bar tại Retest | 2 | Bóng dài > 2 × Body, thân gần mép |
| B2 | Engulfing tại Retest | 2 | Nến Retest nuốt chửng nến trước |
| B3 | Bóng Retest | 1 | Bóng dài > 1.5 × Body (BUY: bóng dưới; SELL: bóng trên) |
| **C. ĐỘNG LƯỢNG** |
| C1 | RSI xác nhận | 1 | BUY: RSI > 55; SELL: RSI < 45 |
| **TỔNG** | | **12** | |

**Ngưỡng vào lệnh:**
- `≥ 8/12` → ✅ có thể vào lệnh.
- `6-7/12` → ⏳ có thể xem xét thêm nếu A1+B1+C1 ≥ 5.
- `< 6/12` → ❌ hủy.

---

## 6. DANH SÁCH BỘ LỌC TÍCH HỢP THÊM HOẶC THAY ĐỔI, KHÔNG TRONG DANH SÁCH THÌ GIỮ NGUYÊN

| # | Bộ lọc | Vai trò |
|---|--------|---------|
| 1 | Vùng Range đủ rộng | Range_width > 2.5×ATR → lọc vùng hẹp |
| 2 | Liquidity Sweep | Phát hiện bóng dài vượt Range rồi đóng cửa trở lại → fake breakout |
| 3 | Breakout Strength | Thân nến lớn, đóng cửa xa Range → xác nhận mạnh |
| 4 | Pin Bar / Engulfing tại Retest | Xác nhận lực đẩy tại vùng Retest |
| 5 | RSI xác nhận | RSI > 55 (BUY) hoặc < 45 (SELL) |

---

**Lưu ý cho Chứng khoán VN:**
- Volume bắt buộc: Volume breakout > 1.8×SMA(Volume,20).
---

## 7. TỔNG KẾT

**Bot BRB V2.0 với Ma trận Xác nhận và SL/TP tối ưu mang lại:**

| Chỉ số | Kỳ vọng |
|--------|---------|
| Win Rate | 65-75% |
| R:R hiệu quả | 1:2 – 1:3 |
| Profit Factor | > 1.8 |
| Max Drawdown | < 10% |
| Tần suất | 1-3 lệnh/ngày |

**Lợi ích chính:**
- Lọc bỏ 80-90% fake breakout qua các tiêu chí điểm số.
- SL được tối ưu để không bị quét thanh khoản.
- Vào lệnh muộn hơn nhưng Win Rate cao hơn.
- Quản lý vốn chặt chẽ, phù hợp với tài khoản nhỏ.
- Thích ứng với nhiều loại tài sản.

---

*Ngày cập nhật: 2026-07-25*  
*Phiên bản: V2.0*