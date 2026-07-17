# TÀI LIỆU THIẾT KẾ BOT GIAO DỊCH ĐA CHIẾN LƯỢC – PHIÊN BẢN CHI TIẾT (V1.2 - UPDATED)
Dành cho: Chuyển đổi sang code Python

> **Thay đổi so với V1.1:**
> 1. Sửa mâu thuẫn công thức SL/TP giữa Chiến lược 2 (Mean Reversion) và pseudo-code vòng lặp chính (mục 5 vs mục 8).
> 2. Hoàn thiện bộ lọc đa khung thời gian (MTF) theo cặp khung cụ thể: 15m→H1, H1→H4, H4→D1, D1→Weekly; và tích hợp bộ lọc DXY vào vòng lặp chính.
> 3. Thêm mục 11 – khuyến nghị giảm bậc tự do và kiểm định thống kê để hạn chế overfitting.
> 4. Thêm bộ lọc rủi ro cấp tài khoản: tối đa 3 lệnh mở đồng thời, tối đa 3 lệnh thua/ngày thì tắt bot đến hết ngày.

---

## MỤC LỤC
1. Triết lý cốt lõi
2. Danh sách bộ lọc nền tảng (14 bộ lọc)
3. Cấu trúc EMA34 và EMA89 – vai trò và cách tích hợp
4. Chiến lược 1: Breakout – Retest (dành cho thị trường xu hướng)
5. Chiến lược 2: Mean Reversion bằng kênh EMA34 (dành cho thị trường đi ngang)
6. Bộ lọc chuyên sâu – chi tiết công thức và tích hợp (Confirmation Lag, Equity Curve, ER, ATR Z-score, MTF, DXY, Account Risk Limit)
7. Phân tham số theo loại tài sản (Forex, Crypto, Chứng khoán)
8. Quy trình vận hành bot (pseudo-code hoàn chỉnh - Đã sửa lỗi SL/TP và bổ sung MTF/DXY/Account Risk)
9. Bảng tổng hợp tham số khuyến nghị để đưa vào code
10. Hướng dẫn backtest và tối ưu
11. Quản lý rủi ro Overfitting và kiểm định tham số (MỚI)
12. Kết luận

---

## 1. TRIẾT LÝ CỐT LÕI (KHÔNG ĐƯỢC THAY ĐỔI)
* Bot là cỗ máy xác suất: không có chiến thắng 100%, mục tiêu là **Positive Expectancy** sau 100+ lệnh.
* Tự động nhận diện trạng thái thị trường (xu hướng mạnh, đi ngang, nhiễu) và chọn chiến lược phù hợp.
* Quản lý rủi ro là trên hết: mỗi lệnh rủi ro 2% tài khoản (ưu tiên 1%).
* Tất cả tín hiệu phải là **xác định (deterministic)**: chỉ dùng số học, không dùng mô hình cần mắt người (trendline thủ công, divergence, mô hình nến phức tạp).

---

## 2. DANH SÁCH 14 BỘ LỌC NỀN TẢNG (ÁP DỤNG CHO MỌI CHIẾN LƯỢC)

| STT | Tên bộ lọc | Công thức / Tham số | Vai trò |
|---|---|---|---|
| 1 | **Xu hướng chính (Trend Filter)** | EMA34_Close, EMA34_High, EMA34_Low, EMA89_Close. So sánh vị trí giá đóng cửa với kênh EMA34 và vị trí EMA34 so với EMA89. | Xác định chế độ BULL, BEAR, hoặc TRUNG TÍNH. |
| 2 | **Cường độ xu hướng (ADX)** | ADX(14) trên khung H1/H4. | ADX > 30 → Kích hoạt Breakout. ADX < 25 → Kích hoạt Mean Reversion. 25–30 → TT. |
| 3 | **Độ mượt xu hướng (Efficiency Ratio - ER)** | ER = \|Close[i] - Close[i-10]\| / sum(\|Close[j] - Close[j-1]\|) (j=i-9..i). | ER > 0.6 → Breakout. ER < 0.3 → Mean Reversion. 0.3–0.6 → TT. Kết hợp với ADX. |
| 4 | **Biến động tham chiếu (ATR)** | ATR(14) tính trên khung thời gian giao dịch chính. | Dùng để tính SL và TP động: SL = 1.5 × ATR; TP = 3 × ATR (có thể điều chỉnh theo chiến lược). |
| 5 | **Biến động tương đối (ATR Spike / Z-score)** | Z-score = (ATR(14) hiện tại – trung bình ATR 100 nến) / độ lệch chuẩn ATR 100 nến. | **Nếu Z > 2.0:** Biến động bùng nổ mạnh → TẮT Mean Reversion, CHỈ cho phép đánh Breakout (SL/TP nhân 1.5 lần). **Nếu Z < -1.5:** Thị trường quá tĩnh → TẮT bot. **Nếu 1.0 < Z <= 2.0:** Tăng SL/TP lên 1.5 lần. |
| 6 | **Khối lượng (Volume) – chỉ cho chứng khoán** | Volume breakout > 1.5 × Volume MA(20). | Xác nhận phá vỡ thật. Nếu không đạt, hủy tín hiệu Breakout. |
| 7 | **Lọc thời gian (Session)** | Forex: London (15–24h) & New York (20–3h) giờ VN. Chứng khoán: giờ mở cửa, trừ 30 phút cuối và né ngày công bố tin tức. | Tránh thanh khoản thấp, giảm nhiễu. |
| 8 | **Lọc đa khung thời gian (MTF)** | Khung giao dịch chính đối chiếu với khung cao hơn liền kề theo cặp cố định: **15m → H1**, **H1 → H4**, **H4 → D1**, **D1 → Weekly**. Xu hướng khung cao hơn (EMA34_Close vs EMA89_Close) phải đồng thuận hoặc trung tính với hướng lệnh. | Nếu khung cao hơn đang BEAR, bot chỉ được SELL (không BUY) trên khung nhỏ hơn, và ngược lại. Xem chi tiết mục 6.5. |
| 9 | **Lọc tương quan (DXY)** | Chỉ áp dụng cho Forex. Nếu DXY tăng > 0.2% trong 1 giờ → CẤM mua các cặp có USD là đồng yết giá (XXX/USD). Nếu DXY giảm > 0.2% trong 1 giờ → CẤM bán các cặp đó. | Giảm rủi ro từ biến động sức mạnh đồng đô la. Xem chi tiết mục 6.6. |
| 10 | **Trễ pha xác nhận (Confirmation Lag)** | Đợi nến tín hiệu đóng cửa, sau đó vào lệnh ở nến tiếp theo nếu giá xác nhận (nến xanh cho Buy, đỏ cho Sell). | Tránh bẫy giá giả, tăng Win Rate. *(Chế độ Normal có thể bỏ qua, Chế độ Advanced áp dụng bắt buộc)*. |
| 11 | **Trạng thái tài khoản (Equity Curve Filter)** | Theo dõi chuỗi thắng/thua gần nhất: thắng >= 3 → giảm risk 50%. Thua >= 2 → giảm risk 30%. | Bảo vệ vốn. **Điểm Reset:** Chuỗi đếm tự động reset về 0 ngay khi có 1 lệnh kết quả ngược lại. *(Xem mục 11 về việc kiểm định lại logic giảm risk khi đang thắng)*. |
| 12 | **Thời gian sống của lệnh (Time Stop)** | Tự động đóng lệnh sau 8 giờ nếu chưa chạm TP1 hoặc SL. | Tránh kẹt lệnh, giải phóng vốn. |
| 13 | **Lọc biến động giá thấp (Range Width)** | Vùng Range (Breakout) phải có biên độ > 1.5 × ATR(14) (ở Chế độ Normal chỉ cần > 1.0 × ATR). | Đảm bảo vùng tích lũy đủ rộng để giao dịch có ý nghĩa. |
| 14 | **Giới hạn rủi ro cấp tài khoản (Account Risk Limit)** *(MỚI)* | Tối đa **3 lệnh mở đồng thời**. Tối đa **3 lệnh thua trong 1 ngày giao dịch** → tắt bot đến khi sang ngày giao dịch mới. | Chặn cả rủi ro quá tải vị thế và chuỗi thua vượt tầm kiểm soát trong ngày xấu. Xem chi tiết mục 6.7. |

---

## 3. CẤU TRÚC EMA34 VÀ EMA89 – VAI TRÒ VÀ CÁCH TÍCH HỢP
**Công thức:**
```text
EMA34_High = EMA(High, 34)
EMA34_Low = EMA(Low, 34)
EMA34_Close = EMA(Close, 34)
EMA89_Close = EMA(Close, 89)
```

**Nguyên tắc xác định chế độ bot:**
```text
IF (Close > EMA34_High) AND (EMA34_Close > EMA89_Close) 
     Chế độ BULL (chỉ tìm BUY)
ELSE IF (Close < EMA34_Low) AND (EMA34_Close < EMA89_Close) 
     Chế độ BEAR (chỉ tìm SELL)
ELSE 
     Chế độ TRUNG TÍNH (NEUTRAL)
END IF
```
*Lưu ý quan trọng:* Đây là bộ lọc xu hướng, KHÔNG phải tín hiệu vào lệnh trực tiếp. Chế độ `TRUNG TÍNH` sẽ TẮT chiến lược Breakout, nhưng **VẪN CHO PHÉP** chạy Chiến lược 2 (Mean Reversion) nếu thỏa mãn bộ lọc $ADX < 25$ và $ER < 0.3$.

---

## 4. CHIẾN LƯỢC 1 – THỊ TRƯỜNG XU HƯỚNG (ADX > 30 và ER > 0.6)
**Tên:** Breakout – Retest với xác nhận khối lượng & EMA34

**Điều kiện kích hoạt:**
* ADX(14) > 30
* ER > 0.6
* Chế độ bot là **BULL (BUY)** hoặc **BEAR (SELL)** từ bộ lọc EMA34/89.

### Phân chế độ lọc: Normal Mode vs Advanced Mode
* **Mode Normal (`ADVANCED_FILTER_MODE = False`) - Tối ưu tốc độ, giảm trễ lệnh:**
  1. Xác định vùng Range (20 nến gần nhất): Range_High = MAX(High, 20), Range_Low = MIN(Low, 20). Đòi hỏi Range_High - Range_Low > 1.0 × ATR(14).
  2. Khi Close > Range_High (hoặc < Range_Low), vào lệnh ngay ở nến tiếp theo hoặc khi giá Retest nhẹ vùng biên (sai số ±0.5%). Không bắt buộc bóng nến rút chân hay nến xác nhận lag.
* **Mode Advanced (`ADVANCED_FILTER_MODE = True`) - Lọc nhiễu tối đa (5 lớp lọc nghiêm ngặt):**
  1. Range Width > 1.5 × ATR(14).
  2. Breakout kèm Volume > 1.5 × MA_Volume_20 (nếu có).
  3. Retest chạm đúng vùng Range với sai số cho phép ±0.3% giá.
  4. Nến tại vùng Retest có bóng (wick) dài về phía ngược lại.
  5. Áp dụng Confirmation Lag: Đợi 1 nến tiếp theo đóng cửa xanh (BUY) hoặc đỏ (SELL) mới vào lệnh.

**Công thức SL/TP (dùng cho Breakout — xem mục 6.8 để đối chiếu với Mean Reversion):**
```text
Entry = Giá mở cửa của nến xác nhận (hoặc giá khớp lệnh chờ).
SL = Range_Low - 0.5*ATR (BUY) hoặc Range_High + 0.5*ATR (SELL).
TP1 = Entry + 1.5*(Entry - SL) [chốt 50%].
TP2 = Entry + 3.0*(Entry - SL) [chốt 50% còn lại].
```
**Quản lý sau khi vào lệnh:**
- Nếu TP1 đạt → kéo SL về hòa vốn cho phần còn lại.
- Nếu sau 8 giờ chưa đạt TP1 → đóng toàn bộ.

---

## 5. CHIẾN LƯỢC 2 – THỊ TRƯỜNG ĐI NGANG (ADX < 25 và ER < 0.3)
**Tên:** Mean Reversion – Giao dịch vùng quá mua/bán bằng kênh EMA34 + RSI

**Điều kiện kích hoạt:**
* ADX(14) < 25
* ER < 0.3
* Chế độ bot có thể là **TRUNG TÍNH (NEUTRAL)**, BULL, hoặc BEAR.

**Các bước thực hiện:**
```text
1. Xác định vùng quá mua (overbought) và quá bán (oversold) động:
   Overbought = EMA34_High + 0.5 * (EMA34_High - EMA34_Close)
   Oversold   = EMA34_Low - 0.5 * (EMA34_Close - EMA34_Low)

2. Đợi giá chạm các vùng này và kết hợp RSI(14):
   IF (Close > Overbought) AND (RSI > 70) AND (Nến tiếp theo đóng cửa đỏ) 
        Lệnh SELL.
   IF (Close < Oversold) AND (RSI < 30) AND (Nến tiếp theo đóng cửa xanh) 
        Lệnh BUY.

3. Áp dụng Confirmation Lag (trễ 1 nến) như chiến lược Breakout.
```

**Công thức SL/TP (RIÊNG cho Mean Reversion — KHÔNG dùng chung công thức ATR14×1.5 của Breakout):**
```text
Entry = Giá mở cửa của nến xác nhận.
SL = EMA34_High + 1*ATR(5)   (đối với SELL)
SL = EMA34_Low  - 1*ATR(5)   (đối với BUY)
TP = EMA34_Close (vùng cân bằng).
```
**Quản lý lệnh:**
- Time Stop = 8 giờ.
- Không kéo SL về hòa vốn vì SL đã rất ngắn.

> ⚠️ **Đây chính là điểm đã sửa (Fix #1):** Ở bản V1.1, pseudo-code vòng lặp chính (mục 8) tính SL/TP theo công thức của Breakout cho CẢ HAI chiến lược, làm sai lệch hoàn toàn logic Mean Reversion ở trên. Ở V1.2, hàm tính SL/TP trong `main_loop()` đã được tách thành 2 nhánh riêng theo `strategy` — xem mục 8, bước 10.

---

## 6. BỘ LỌC CHUYÊN SÂU – CHI TIẾT CÔNG THỨC VÀ TÍCH HỢP

### 6.1. Confirmation Lag
```python
if ADVANCED_FILTER_MODE:
    signal_candle_close = close[-1]
    if signal == "BUY" and close[0] > signal_candle_close:
        entry_price = open[0]  # mở cửa của nến hiện tại (nến tiếp theo)
    elif signal == "SELL" and close[0] < signal_candle_close:
        entry_price = open[0]
    else:
        entry_price = None  # chưa xác nhận, bỏ qua tín hiệu
else:
    entry_price = open[0]  # Chế độ Normal vào lệnh trực tiếp không chờ lag
```

### 6.2. Equity Curve Filter
```python
if last_trade_result == "WIN":
    consecutive_wins += 1
    consecutive_losses = 0  # RESET chuỗi thua về 0 khi có 1 lệnh thắng
elif last_trade_result == "LOSS":
    consecutive_losses += 1
    consecutive_wins = 0    # RESET chuỗi thắng về 0 khi có 1 lệnh thua

if consecutive_wins >= 3:
    risk_multiplier = 0.5
elif consecutive_losses >= 2:
    risk_multiplier = 0.3
else:
    risk_multiplier = 1.0

lot_size = base_lot * risk_multiplier
```
> Xem mục 11 để biết vì sao logic "giảm risk khi đang thắng" nên được kiểm định bằng backtest trước khi giữ nguyên, thay vì áp dụng mặc định.

### 6.3. Efficiency Ratio (ER)
```python
def efficiency_ratio(close_prices, period=10):
    movement = abs(close_prices[-1] - close_prices[-period])
    noise = sum(abs(close_prices[i] - close_prices[i-1]) for i in range(-period+1, 0))
    return movement / noise if noise != 0 else 0
```

### 6.4. ATR Spike (Z-score)
```python
atr_values = [atr(i) for i in range(-100, 0)]  # 100 giá trị gần nhất
mean_atr = mean(atr_values)
std_atr = stdev(atr_values)
z_score = (atr_current - mean_atr) / std_atr

if z_score < -1.5:
    bot_mode = "OFF"
elif z_score > 2.0:
    allow_mean_reversion = False
    allow_breakout = True
    sl_multiplier = 1.5
elif 1.0 < z_score <= 2.0:
    allow_mean_reversion = True
    allow_breakout = True
    sl_multiplier = 1.5
else:
    allow_mean_reversion = True
    allow_breakout = True
    sl_multiplier = 1.0
```

### 6.5. Lọc đa khung thời gian (MTF) — HOÀN THIỆN (Fix #2)
Cặp khung được cố định theo yêu cầu: **15m→H1, H1→H4, H4→D1, D1→Weekly**. Nếu khung chính đã là Weekly thì bỏ qua bộ lọc này (không có khung cao hơn để đối chiếu).

```python
TIMEFRAME_HIERARCHY = {
    "15m": "1H",
    "1H":  "4H",
    "4H":  "1D",
    "1D":  "1W",
}

def check_mtf_trend(symbol, entry_timeframe, signal_direction):
    higher_tf = TIMEFRAME_HIERARCHY.get(entry_timeframe)
    if higher_tf is None:
        return True  # đã là khung cao nhất (Weekly), không có gì để đối chiếu

    htf_data = fetch_ohlcv(symbol, higher_tf, n_bars=200)
    htf_close = htf_data['close']
    htf_ema34_close = EMA(htf_close, 34)
    htf_ema89_close = EMA(htf_close, 89)

    if htf_ema34_close[-1] > htf_ema89_close[-1]:
        htf_trend = "BULL"
    elif htf_ema34_close[-1] < htf_ema89_close[-1]:
        htf_trend = "BEAR"
    else:
        htf_trend = "NEUTRAL"

    # NEUTRAL ở khung lớn hơn không cấm lệnh, chỉ cấm khi NGƯỢC xu hướng rõ ràng
    if signal_direction == "BUY" and htf_trend == "BEAR":
        return False
    if signal_direction == "SELL" and htf_trend == "BULL":
        return False
    return True
```
*Giả định thiết kế cần lưu ý:* khi khung lớn hơn là NEUTRAL, bộ lọc KHÔNG chặn lệnh (chỉ chặn khi ngược chiều rõ ràng). Nếu muốn khắt khe hơn (chỉ cho vào lệnh khi khung lớn đồng thuận rõ ràng, NEUTRAL cũng bị chặn), đổi điều kiện `return False` thành áp dụng cho cả trường hợp `htf_trend == "NEUTRAL"`. Nên test A/B cả hai cách trong backtest vì đây là một tham số có ảnh hưởng lớn đến tần suất lệnh.

### 6.6. Lọc tương quan DXY — HOÀN THIỆN (Fix #2)
```python
DXY_CHANGE_THRESHOLD = 0.2  # % thay đổi trong 1 giờ

def check_dxy_filter(symbol, signal_direction):
    if SYMBOL_TYPE != "FOREX":
        return True
    if "USD" not in symbol:
        return True

    dxy_change_1h = get_dxy_change_percent(lookback_hours=1)
    is_usd_base = symbol.startswith("USD")  # vd: USDJPY -> USD là base

    if dxy_change_1h > DXY_CHANGE_THRESHOLD:
        # DXY tăng mạnh -> USD đang mạnh lên
        if not is_usd_base and signal_direction == "BUY":
            return False   # cấm mua cặp XXX/USD (vd EURUSD) khi USD đang mạnh lên
        if is_usd_base and signal_direction == "SELL":
            return False   # cấm bán USD/XXX khi USD đang mạnh lên
    elif dxy_change_1h < -DXY_CHANGE_THRESHOLD:
        # DXY giảm mạnh -> USD đang yếu đi
        if not is_usd_base and signal_direction == "SELL":
            return False
        if is_usd_base and signal_direction == "BUY":
            return False

    return True
```
*Lưu ý:* bản gốc chỉ mô tả trường hợp DXY tăng. Nhánh DXY giảm được thêm vào cho đối xứng logic — cần backtest riêng để xác nhận có cải thiện performance hay không trước khi giữ lại.

### 6.7. Giới hạn rủi ro cấp tài khoản — MỚI (Fix #4)
```python
MAX_CONCURRENT_TRADES = 3   # tối đa 3 lệnh mở đồng thời
DAILY_MAX_LOSSES = 3        # tối đa 3 lệnh thua/ngày -> tắt bot đến hết ngày

daily_loss_count = 0
current_trading_day = None

def reset_daily_counter_if_new_day():
    global daily_loss_count, current_trading_day
    today = get_current_trading_day()  # định nghĩa "ngày giao dịch" theo giờ chốt phiên đã chọn
    if today != current_trading_day:
        current_trading_day = today
        daily_loss_count = 0

def check_account_risk_limits():
    reset_daily_counter_if_new_day()

    if daily_loss_count >= DAILY_MAX_LOSSES:
        return False, "daily_loss_limit_reached"

    if count_open_trades() >= MAX_CONCURRENT_TRADES:
        return False, "max_concurrent_trades_reached"

    return True, "ok"

def on_trade_closed(result):
    global daily_loss_count
    if result == "LOSS":
        daily_loss_count += 1
    # (consecutive_wins/losses cho Equity Curve Filter cập nhật riêng ở mục 6.2)
```
*Khuyến nghị nâng cao (tùy chọn, chưa bắt buộc theo yêu cầu hiện tại):* khi có 3 lệnh mở đồng thời trên các cặp tương quan cao (vd EURUSD + GBPUSD cùng hướng BUY), rủi ro thực tế lớn hơn 3 lệnh độc lập. Có thể cân nhắc thêm bước kiểm tra hệ số tương quan giữa các symbol đang mở trước khi cho phép mở lệnh thứ 2, 3 — nhưng đây là cải tiến thêm, không phải lỗi cần sửa ngay.

### 6.8. Bảng đối chiếu nhanh SL/TP theo chiến lược (để tránh nhầm lẫn khi code)

| | Breakout | Mean Reversion |
|---|---|---|
| SL | `Range_Low/High ± 0.5×ATR(14)` | `EMA34_High/Low ± 1×ATR(5)` |
| TP | `Entry ± 1.5×(Entry-SL)` (TP1), `± 3.0×(Entry-SL)` (TP2) | `EMA34_Close` (mục tiêu duy nhất, không chia TP1/TP2) |
| Kéo SL hòa vốn | Có, khi đạt TP1 | Không (SL đã rất ngắn) |
| sl_scale (Z-score) | Nhân vào khoảng cách SL | Không áp dụng (SL đã dựa theo ATR(5) ngắn hạn riêng) |

---

## 7. PHÂN THAM SỐ THEO LOẠI TÀI SẢN

| Tham số | Forex (EURUSD, GBPUSD) | Crypto (BTC/USD, ETH/USD) | Chứng khoán Mỹ (AAPL, TSLA) |
|---|---|---|---|
| Khung thời gian chính | H1 (15m-1H) | H1 (1H) | Daily (H1 cho scalping) |
| ADX ngưỡng xu hướng | > 30 (mạnh), < 25 (yếu) | > 35 (mạnh), < 20 (yếu) | > 30 (mạnh), < 25 (yếu) |
| ER ngưỡng | > 0.6 (mượt), < 0.35 (nhiễu) | > 0.65 (mượt), < 0.3 (nhiễu) | > 0.6 (mượt), < 0.35 (nhiễu) |
| ATR(14) chu kỳ | 14 (mặc định) | 14 (có thể 10 cho thanh khoản thấp) | 14 (hoặc 20 cho cổ phiếu vốn hóa lớn) |
| Z-score ngưỡng | > 2.0 (chỉ Breakout), < -1.5 (OFF) | > 2.5 (chỉ Breakout), < -1.5 (OFF) | > 2.0 (chỉ Breakout), < -1.5 (OFF) |
| SL/TP cho Breakout | SL=1.5xATR, TP1=1.5xSL, TP2=3xSL | SL=2xATR, TP1=1.5xSL, TP2=3.5xSL | SL=1.5xATR, TP1=1.5xSL, TP2=3xSL |
| SL/TP cho Mean Reversion | SL=1xATR(5), TP=EMA34_Close | SL=1.5xATR(5), TP=EMA34_Close | SL=1xATR(5), TP=EMA34_Close |
| Volume filter | KHÔNG dùng | KHÔNG dùng | Dùng: Volume breakout > 1.5×MA20 |
| Session Filter | London & New York | 24/7 (tránh cuối tuần) | Giờ mở cửa (9:30-16:00 NY) |
| Mode Lọc Breakout | Normal / Advanced | Normal / Advanced | Normal / Advanced |
| Risk per trade | 1-2% | 1-1.5% | 1-1.5% |

> ⚠️ Xem mục 11: bảng tham số riêng theo từng loại tài sản này là một trong những nguồn overfitting lớn nhất của thiết kế — mỗi cột thêm là thêm một bộ bậc tự do được "may đo" riêng.

---

## 8. QUY TRÌNH VẬN HÀNH BOT (PSEUDO-CODE HOÀN CHỈNH – V1.2, ĐÃ SỬA SL/TP + BỔ SUNG MTF/DXY/ACCOUNT RISK)

```python
def main_loop():
    # 0. Kiểm tra giới hạn rủi ro cấp tài khoản TRƯỚC KHI làm bất cứ điều gì khác
    ok, reason = check_account_risk_limits()
    if not ok:
        return reason  # "daily_loss_limit_reached" hoặc "max_concurrent_trades_reached"

    # 1. Lấy dữ liệu OHLC, Volume (nếu có)
    data = fetch_ohlcv(symbol, timeframe, n_bars=200)
    close = data['close']; high = data['high']; low = data['low']; volume = data['volume']

    # 2. Tính toán tất cả chỉ báo
    ema34_high = EMA(high, 34)
    ema34_low = EMA(low, 34)
    ema34_close = EMA(close, 34)
    ema89_close = EMA(close, 89)
    adx = ADX(high, low, close, 14)
    rsi = RSI(close, 14)
    atr14 = ATR(high, low, close, 14)
    atr5 = ATR(high, low, close, 5)
    er = efficiency_ratio(close, 10)
    z_atr = zscore_atr(atr14, 100)
    volume_ma20 = SMA(volume, 20)

    # 3. Lọc thời gian & sự kiện
    if not is_valid_session():
        return "wait"
    if is_news_event(symbol):
        return "wait"

    # 4. Lọc ATR Spike (Z-score)
    if z_atr < -1.5:
        return "off"
    elif z_atr > 2.0:
        allow_mean_reversion = False
        allow_breakout = True
        sl_scale = 1.5
    elif z_atr > 1.0:
        allow_mean_reversion = True
        allow_breakout = True
        sl_scale = 1.5
    else:
        allow_mean_reversion = True
        allow_breakout = True
        sl_scale = 1.0

    # 5. Xác định trạng thái xu hướng EMA34/89 (khung chính)
    if close[-1] > ema34_high[-1] and ema34_close[-1] > ema89_close[-1]:
        mode = "BULL"
    elif close[-1] < ema34_low[-1] and ema34_close[-1] < ema89_close[-1]:
        mode = "BEAR"
    else:
        mode = "NEUTRAL"

    # 6. Lựa chọn chiến lược dựa trên ADX và ER
    strategy = None
    if adx[-1] > 30 and er > 0.6 and allow_breakout:
        if mode in ["BULL", "BEAR"]:
            strategy = "BREAKOUT"
    elif adx[-1] < 25 and er < 0.3 and allow_mean_reversion:
        strategy = "MEAN_REVERSION"

    if strategy is None:
        return "wait"

    # 7. Áp dụng Equity Curve Filter
    risk_multiplier = get_equity_multiplier()

    # 8. Tìm tín hiệu cụ thể theo chiến lược
    if strategy == "BREAKOUT":
        signal = find_breakout_retest(data, ema34_high, ema34_low, volume_ma20, advanced_mode=ADVANCED_FILTER_MODE)
    else:  # MEAN_REVERSION
        signal = find_mean_reversion(data, ema34_high, ema34_low, ema34_close, rsi)

    if signal is None:
        return "no_signal"

    # 9. Confirmation Lag (nếu Advanced Mode)
    if ADVANCED_FILTER_MODE and not confirm_lag(signal, data):
        return "no_confirm"

    # 9b. Lọc MTF — đối chiếu với khung cao hơn liền kề (Fix #2)
    if not check_mtf_trend(symbol, timeframe, signal.direction):
        return "mtf_conflict"

    # 9c. Lọc DXY — chỉ áp dụng cho Forex (Fix #2)
    if not check_dxy_filter(symbol, signal.direction):
        return "dxy_conflict"

    # 10. Tính SL, TP theo ĐÚNG chiến lược (Fix #1 — tách 2 nhánh riêng biệt)
    entry_price = signal.entry

    if strategy == "BREAKOUT":
        if signal.direction == "BUY":
            sl_price = signal.range_low - 0.5 * atr14[-1] * sl_scale
        else:
            sl_price = signal.range_high + 0.5 * atr14[-1] * sl_scale
        tp1_price = entry_price + 1.5 * abs(entry_price - sl_price) if signal.direction == "BUY" \
            else entry_price - 1.5 * abs(entry_price - sl_price)
        tp2_price = entry_price + 3.0 * abs(entry_price - sl_price) if signal.direction == "BUY" \
            else entry_price - 3.0 * abs(entry_price - sl_price)
        use_partial_tp = True

    else:  # MEAN_REVERSION — công thức RIÊNG, không dùng ATR14 của Breakout
        if signal.direction == "BUY":
            sl_price = ema34_low[-1] - 1.0 * atr5[-1]
        else:
            sl_price = ema34_high[-1] + 1.0 * atr5[-1]
        tp1_price = ema34_close[-1]   # mục tiêu duy nhất là vùng cân bằng EMA34_Close
        tp2_price = None              # không chia TP1/TP2 ở Mean Reversion
        use_partial_tp = False

    # 11. Tính khối lượng lệnh
    lot_size = calculate_lot(risk_percent=1.0 * risk_multiplier, sl_distance=abs(entry_price - sl_price))

    # 11b. Kiểm tra lại giới hạn tài khoản NGAY TRƯỚC KHI gửi lệnh
    # (phòng trường hợp có lệnh khác vừa mở/đóng trong lúc xử lý tín hiệu)
    ok, reason = check_account_risk_limits()
    if not ok:
        return reason

    # 12. Gửi lệnh
    order_id = place_order(symbol, signal.direction, lot_size, entry_price, sl_price,
                            tp1_price, tp2_price, use_partial_tp=use_partial_tp)

    # 13. Giám sát lệnh (vòng lặp phụ)
    monitor_order(order_id, time_stop_hours=8, allow_breakeven_after_tp1=use_partial_tp)

    return "done"


def on_order_closed(order_id, result):
    # Gọi khi 1 lệnh đóng (TP/SL/Time Stop) — cập nhật CẢ HAI bộ đếm
    update_equity_curve(result)      # mục 6.2 — consecutive_wins/losses
    on_trade_closed(result)          # mục 6.7 — daily_loss_count
```

---

## 9. BẢNG TỔNG HỢP THAM SỐ KHUYẾN NGHỊ ĐỂ ĐƯA VÀO CODE

```python
# ========== CẤU HÌNH CHUNG ==========
SYMBOL_TYPE = "FOREX"  # "FOREX", "CRYPTO", "STOCK"
TIMEFRAME = "1H"
MAX_RISK_PER_TRADE = 1.0  # % tài khoản
MAX_CONCURRENT_TRADES = 3   # cập nhật theo yêu cầu: tối đa 3 lệnh mở đồng thời
DAILY_MAX_LOSSES = 3        # tối đa 3 lệnh thua/ngày -> tắt bot đến hết ngày giao dịch
TIME_STOP_HOURS = 8

# ========== CẤU HÌNH CHẾ ĐỘ LỌC BREAKOUT ==========
ADVANCED_FILTER_MODE = False

# ========== BỘ LỌC ==========
ADX_THRESHOLD_TREND = 30
ADX_THRESHOLD_RANGE = 25
ER_THRESHOLD_TREND = 0.6
ER_THRESHOLD_RANGE = 0.3
Z_SCORE_OFF_LOW = -1.5
Z_SCORE_BREAKOUT_ONLY = 2.0

# ========== EMA34/89 ==========
EMA_FAST = 34
EMA_SLOW = 89
USE_HIGH_LOW_EMA = True

# ========== CHIẾN LƯỢC BREAKOUT ==========
RANGE_PERIOD = 20
BREAKOUT_VOLUME_MULTIPLIER = 1.5
RETEST_TOLERANCE_NORMAL = 0.005
RETEST_TOLERANCE_ADVANCED = 0.003

# ========== CHIẾN LƯỢC MEAN REVERSION ==========
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MR_SL_ATR_PERIOD = 5
MR_SL_MULTIPLIER = 1.0
MR_TP_TARGET = "EMA34_CLOSE"

# ========== QUẢN LÝ VỐN & EQUITY CURVE FILTER ==========
EQUITY_WIN_STREAK_REDUCE = 0.5
EQUITY_LOSS_STREAK_REDUCE = 0.3
CONSECUTIVE_WINS_TRIGGER = 3
CONSECUTIVE_LOSSES_TRIGGER = 2
RESET_STREAK_ON_OPPOSITE_TRADE = True

# ========== LỌC ĐA KHUNG THỜI GIAN (MTF) — MỚI ==========
TIMEFRAME_HIERARCHY = {
    "15m": "1H",
    "1H":  "4H",
    "4H":  "1D",
    "1D":  "1W",
}
MTF_BLOCK_ON_NEUTRAL = False  # False: NEUTRAL khung lớn không chặn lệnh; True: chỉ vào khi khung lớn đồng thuận rõ ràng

# ========== LỌC DXY — MỚI ==========
DXY_CHANGE_THRESHOLD = 0.2  # % thay đổi trong 1 giờ

# ========== THỜI GIAN ==========
# Forex: 15-24h và 20-3h giờ VN (London + New York)
# Crypto: 24/7 nhưng tránh cuối tuần
# Stock: 9:30-16:00 (NY time) trừ 30p cuối

# ========== LỌC TIN TỨC ==========
NEWS_BLACKLIST = []
```

---

## 10. HƯỚNG DẪN BACKTEST VÀ TỐI ƯU
* **Backtest cơ bản:** Chạy trên dữ liệu 2 năm, tối thiểu 500 lệnh. Theo dõi Win Rate, Profit Factor, Maximum Drawdown, Sharpe Ratio, Expectancy.
* **Tối ưu tham số:** Walk-Forward (70% optimize / 30% test). Không tối ưu quá mức — xem mục 11 để biết cách kiểm định nghiêm ngặt hơn.
* **So sánh Normal vs Advanced Mode:** backtest độc lập để xác định chế độ nào có Expectancy cao hơn trên từng loại tài sản.
* **So sánh MTF_BLOCK_ON_NEUTRAL = True vs False:** vì đây là tham số mới thêm, cần test cả 2 giá trị trước khi chốt.
* **Kiểm tra độ nhạy:** Thay đổi ngưỡng ADX/ER một vài đơn vị để xem kết quả có đột biến không.
* Luôn backtest với phí giao dịch (spread, commission, slippage) để có kết quả thực tế.

---

## 11. QUẢN LÝ RỦI RO OVERFITTING VÀ KIỂM ĐỊNH THAM SỐ (MỚI)

Thiết kế hiện có khoảng 20 tham số ngưỡng (ADX, ER, Z-score, RSI, retest tolerance, equity streak, DXY threshold, MTF...) nhân với bảng tham số riêng cho 3 loại tài sản. Đây là nhiều bậc tự do — rủi ro lớn nhất không phải là ý tưởng sai, mà là **bộ tham số được "may đo" vừa khít với đúng đoạn dữ liệu đã backtest và mất tác dụng khi ra dữ liệu mới**. Các gợi ý cụ thể:

### 11.1. Giảm bớt bậc tự do trước khi tối ưu
- **Gộp bảng tham số theo tài sản** (mục 7) thành một bộ chuẩn hóa động: thay vì "ADX > 30 cho Forex, > 35 cho Crypto", dùng percentile của ADX so với 100-200 nến gần nhất của chính symbol đó (vd "ADX nằm trong top 30% giá trị gần đây"). Cách này giảm được ~6-8 tham số cố định cứng theo từng loại tài sản.
- Cân nhắc **bỏ bớt một trong hai chỉ báo regime** (ADX hoặc ER) nếu backtest cho thấy chúng cho tín hiệu trùng lặp hơn 80% thời gian — giữ cả hai chỉ để redundant không tăng thêm giá trị, chỉ tăng thêm tham số cần tối ưu.
- Với `MTF_BLOCK_ON_NEUTRAL` và nhánh DXY-giảm mới thêm ở mục 6.6: coi đây là **giả thuyết cần kiểm chứng**, không mặc định bật, vì mỗi lựa chọn true/false cũng là một bậc tự do.

### 11.2. Walk-Forward nên chạy nhiều cửa sổ, không chỉ 1 lần
- Thay vì chia 1 lần 70/30, dùng **Rolling Walk-Forward**: vd tối ưu 6 tháng → test 2 tháng → trượt cửa sổ tới → lặp lại 8-10 lần trên toàn bộ 2 năm dữ liệu. Nếu bộ tham số tối ưu thay đổi mạnh giữa các cửa sổ, đó là dấu hiệu tham số không ổn định (dễ overfit).
- Với dữ liệu tài chính có tính chất chuỗi thời gian chồng lấn (nhiều lệnh dùng chung nến), nên cân nhắc kỹ thuật **Purged & Embargoed Cross-Validation** (López de Prado) để tránh rò rỉ thông tin giữa tập train/test.

### 11.3. Kiểm định thống kê thay vì chỉ nhìn lợi nhuận backtest
- **Kiểm tra độ vững bằng "heatmap" tham số:** vẽ hiệu suất (Expectancy/Sharpe) khi thay đổi từng tham số ±10-20% quanh giá trị đã chọn. Nếu hiệu suất sụp đổ ngay khi lệch nhẹ khỏi điểm tối ưu, đó là overfit vào 1 điểm dữ liệu cụ thể — nên chọn vùng tham số "cao nguyên" ổn định thay vì đỉnh nhọn.
- **Monte Carlo permutation test:** xáo trộn ngẫu nhiên thứ tự chuỗi kết quả lệnh (hoặc entry ngẫu nhiên cùng luật SL/TP/thoát lệnh) hàng nghìn lần để xem kết quả gốc có vượt trội so với phân phối ngẫu nhiên một cách có ý nghĩa thống kê hay không.
- **Deflated Sharpe Ratio / Probabilistic Sharpe Ratio:** vì đã thử nhiều tổ hợp tham số (multiple testing), Sharpe Ratio thô sẽ bị thổi phồng — các chỉ số này điều chỉnh lại cho số lần thử.
- **So sánh với benchmark đơn giản:** entry ngẫu nhiên nhưng dùng cùng ATR-based SL/TP và cùng bộ lọc thời gian/session. Nếu bot không vượt trội rõ rệt so với baseline này, phần "thông minh" của bộ lọc (breakout/mean-reversion logic) chưa chứng minh được giá trị thật.

### 11.4. Kiểm tra tổng quát hóa (generalization) qua nhiều tài sản
- Chạy CÙNG một bộ tham số (không tối ưu riêng) trên nhiều cặp Forex khác nhau (EURUSD, GBPUSD, USDJPY...) cùng lúc. Nếu hiệu suất chỉ tốt trên 1-2 cặp đã dùng để tối ưu và kém hẳn trên các cặp khác cùng nhóm, đó là dấu hiệu overfit vào đặc thù của riêng cặp đó chứ không phải một edge thật.

### 11.5. Trước khi chạy tiền thật
- **Forward test/demo tối thiểu vài trăm lệnh** sau backtest, để so sánh: Win Rate, Expectancy, slippage thực tế vs backtest. Nếu lệch quá xa (>20-30%), quay lại kiểm tra giả định trong backtest (spread, độ trễ khớp lệnh).
- Bắt đầu tiền thật với **risk per trade thấp hơn mức tối ưu backtest** (vd dùng 0.5% thay vì 1% ban đầu) trong giai đoạn xác nhận đầu tiên.

---

## 12. KẾT LUẬN
Tài liệu V1.2 đã: (1) sửa mâu thuẫn công thức SL/TP giữa Chiến lược 2 và vòng lặp chính, (2) hoàn thiện và tích hợp bộ lọc MTF (theo cặp khung 15m→H1→H4→D1→Weekly) và DXY vào `main_loop()`, (3) bổ sung mục kiểm định overfitting với các phương pháp cụ thể (Walk-Forward nhiều cửa sổ, Monte Carlo, Deflated Sharpe, kiểm tra đa tài sản), (4) thêm giới hạn rủi ro cấp tài khoản (tối đa 3 lệnh đồng thời, tối đa 3 lệnh thua/ngày). Trước khi đưa vào code production, nên ưu tiên chạy các bước ở mục 11 để xác nhận bộ tham số không chỉ đẹp trên backtest mà còn ổn định qua nhiều điều kiện thị trường khác nhau.
