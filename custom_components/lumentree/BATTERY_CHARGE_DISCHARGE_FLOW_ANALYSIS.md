# PHÂN TÍCH TOÀN BỘ FLOW: Battery Charge & Discharge

## 📊 TỔNG QUAN

Tài liệu này trace toàn bộ quá trình xử lý dữ liệu battery charge và discharge từ API đến hiển thị trên dashboard.

---

## 🔄 FLOW XỬ LÝ DỮ LIỆU

### **BƯỚC 1: API Response (HTTP API)**

**Endpoint:** `/lesvr/getBatDayData?deviceId={id}&queryDate={date}`

**Response Structure:**
```json
{
  "returnValue": 1,
  "data": {
    "bats": [
      {
        "tableValue": 290,  // Charge total (0.1 kWh) → 29.0 kWh
      },
      {
        "tableValue": 150,  // Discharge total (0.1 kWh) → 15.0 kWh
      }
    ],
    "tableValueInfo": [
      // 288 giá trị signed (5 phút/lần)
      // Positive = Charge (pin nhận năng lượng)
      // Negative = Discharge (pin phát năng lượng)
      500, 500, 450,  // Charge (dương)
      -200, -300, -400,  // Discharge (âm)
      0, 0, 0,  // Không có hoạt động
      ...
    ]
  }
}
```

**Quy ước API:**
- ✅ `tableValueInfo`: Signed values
  - **Positive (+)** = Charge (pin nhận năng lượng)
  - **Negative (-)** = Discharge (pin phát năng lượng)
- ✅ `bats[0].tableValue`: Charge total (0.1 kWh units)
- ✅ `bats[1].tableValue`: Discharge total (0.1 kWh units)

---

### **BƯỚC 2: API Client Processing** (`api_client.py`)

**File:** `custom_components/lumentree/core/api_client.py`  
**Method:** `_fetch_battery_data()`

#### 2.1. Lấy daily totals:
```python
# Dòng 611-614
if len(bats_data) > 0 and "tableValue" in bats_data[0]:
    result["charge_today"] = float(bats_data[0]["tableValue"]) / 10.0  # 290 → 29.0 kWh
if len(bats_data) > 1 and "tableValue" in bats_data[1]:
    result["discharge_today"] = float(bats_data[1]["tableValue"]) / 10.0  # 150 → 15.0 kWh
```

✅ **ĐÚNG** - Chia 10 để convert từ 0.1 kWh → kWh

#### 2.2. Xử lý series 5 phút:
```python
# Dòng 618-631
series_w = self._to_float_list(data.get("tableValueInfo"))
if series_w:
    # Charge: keep positive values, convert to kWh
    charge_kwh5 = self._series_5min_kwh([w if w > 0 else 0.0 for w in series_w])
    # Discharge: keep negative values (don't invert!), convert absolute value to kWh
    discharge_kwh5 = self._series_5min_kwh([abs(w) if w < 0 else 0.0 for w in series_w])
    result.update({
        "battery_series_5min_w": series_w,  # ← GIỮ NGUYÊN SIGNED VALUES
        "battery_charge_series_hour_kwh": self._series_hour_kwh(charge_kwh5),
        "battery_discharge_series_hour_kwh": self._series_hour_kwh(discharge_kwh5),
    })
```

**Phân tích:**
- ✅ `battery_series_5min_w`: Giữ nguyên signed values (positive/negative) - **ĐÚNG**
- ✅ `charge_kwh5`: Lấy w > 0, convert sang kWh - **ĐÚNG**
- ✅ `discharge_kwh5`: Lấy abs(w) nếu w < 0, convert sang kWh - **ĐÚNG** (vì kWh phải là số dương)

**Kết quả:**
```python
{
    "charge_today": 29.0,  # kWh
    "discharge_today": 15.0,  # kWh
    "battery_series_5min_w": [500, 500, -200, -300, 0, ...],  # Signed W
    "battery_charge_series_hour_kwh": [...],  # Hourly charge kWh
    "battery_discharge_series_hour_kwh": [...],  # Hourly discharge kWh
}
```

---

### **BƯỚC 3: Coordinator** (`daily_coordinator.py`)

**File:** `custom_components/lumentree/coordinators/daily_coordinator.py`  
**Method:** `_async_update_data()`

```python
# Dòng 57
new_data = await self.api.get_daily_stats(self.device_sn, today_str)
```

**`get_daily_stats()` làm gì:**
- Gọi `_fetch_battery_data()` và merge vào result
- Trả về data với `charge_today`, `discharge_today`, `battery_series_5min_w`

✅ **ĐÚNG** - Chỉ pass through, không xử lý thêm

---

### **BƯỚC 4: Sensor Entity** (`sensor.py`)

**File:** `custom_components/lumentree/entities/sensor.py`  
**Class:** `LumentreeDailyStatsSensor`

#### 4.1. Native value (daily total):
```python
# Dòng 333-343 (charge_today)
@property
def native_value(self) -> float | None:
    return float(self.coordinator.data.get("charge_today") or 0.0)

# Dòng 342-352 (discharge_today)
@property
def native_value(self) -> float | None:
    return float(self.coordinator.data.get("discharge_today") or 0.0)
```

✅ **ĐÚNG** - Lấy trực tiếp từ coordinator data

#### 4.2. Series 5min_w attribute:
```python
# Dòng 972-991
if key in (KEY_DAILY_CHARGE_KWH, KEY_DAILY_DISCHARGE_KWH):
    battery_series = self.coordinator.data.get("battery_series_5min_w")
    if battery_series and isinstance(battery_series, list):
        if key == KEY_DAILY_CHARGE_KWH:
            # Charge: keep positive values, set negative to 0
            attrs["series_5min_w"] = [w if w > 0 else 0.0 for w in battery_series]
        else:  # discharge
            # Discharge: keep negative values (don't invert!), set positive to 0
            attrs["series_5min_w"] = [w if w < 0 else 0.0 for w in battery_series]
```

**Phân tích:**
- ✅ **Charge**: `[w if w > 0 else 0.0]` - Lấy giá trị dương, set âm = 0 - **ĐÚNG**
- ✅ **Discharge**: `[w if w < 0 else 0.0]` - Lấy giá trị âm, set dương = 0 - **ĐÚNG**

**Ví dụ:**
```python
battery_series = [500, 500, -200, -300, 0, 100, -150]

# Charge sensor:
attrs["series_5min_w"] = [500, 500, 0, 0, 0, 100, 0]  # ✅ ĐÚNG

# Discharge sensor:
attrs["series_5min_w"] = [0, 0, -200, -300, 0, 0, -150]  # ✅ ĐÚNG (giữ nguyên âm)
```

---

### **BƯỚC 5: Dashboard** (`dashboard_battery_charge_discharge.yaml`)

#### 5.1. Charge series:
```javascript
// Dòng 65-80
const val = parseFloat(value) || 0;
return [timestamp.getTime(), Math.min(Math.max(val, 0), 4000)];
```

✅ **ĐÚNG** - Clamp 0-4000W, giá trị đã là dương

#### 5.2. Discharge series:
```javascript
// Dòng 87-106 (SAU KHI SỬA)
const val = parseFloat(value) || 0;
// Discharge values are already negative from sensor (w < 0)
// Clamp absolute value to 0-3000, then keep negative sign
const absVal = Math.abs(val);
const clamped = Math.min(Math.max(absVal, 0), 3000);
return [timestamp.getTime(), -clamped];
```

**Phân tích:**
- ✅ Lấy `abs(val)` trước khi clamp - **ĐÚNG**
- ✅ Clamp 0-3000 - **ĐÚNG**
- ✅ Đảo dấu thành âm `-clamped` - **ĐÚNG**

**Ví dụ:**
```javascript
val = -500  // Từ sensor (đã là âm)
absVal = 500
clamped = 500
return [-500]  // ✅ Hiển thị dưới 0
```

---

## ✅ KẾT LUẬN

### **Flow đã ĐÚNG sau khi sửa:**

1. ✅ **API**: Trả về signed values (positive = charge, negative = discharge)
2. ✅ **API Client**: 
   - Giữ nguyên signed trong `battery_series_5min_w`
   - Tính charge/discharge totals đúng
3. ✅ **Sensor Entity**:
   - Charge: Lấy giá trị dương
   - Discharge: Lấy giá trị âm (giữ nguyên)
4. ✅ **Dashboard**:
   - Charge: Clamp 0-4000W
   - Discharge: Clamp absolute value 0-3000W, giữ dấu âm

### **Các thay đổi đã thực hiện:**

1. ✅ `sensor.py`: Discharge giữ nguyên giá trị âm (không đảo dấu)
2. ✅ `api_client.py`: Dùng `abs()` khi tính discharge_kwh5
3. ✅ `dashboard_battery_charge_discharge.yaml`: Sửa logic clamp cho discharge

---

## 🔍 KIỂM TRA THỰC TẾ

### **Test case:**

**Input từ API:**
```json
"tableValueInfo": [500, 500, -200, -300, 0, 100, -150]
```

**Expected output:**

1. **Charge sensor `series_5min_w`:**
   ```python
   [500, 500, 0, 0, 0, 100, 0]
   ```
   ✅ Hiển thị trên 0

2. **Discharge sensor `series_5min_w`:**
   ```python
   [0, 0, -200, -300, 0, 0, -150]
   ```
   ✅ Hiển thị dưới 0

3. **Dashboard:**
   - Charge: [500, 500, 0, 0, 0, 100, 0] → Hiển thị trên 0
   - Discharge: [0, 0, -200, -300, 0, 0, -150] → Hiển thị dưới 0

---

## ⚠️ LƯU Ý

1. **API convention:**
   - Positive = Charge (pin nhận năng lượng)
   - Negative = Discharge (pin phát năng lượng)
   - Đây là quy ước của API, không phải lỗi

2. **Daily totals:**
   - `charge_today` và `discharge_today` luôn là số dương (kWh)
   - Chỉ `series_5min_w` mới có giá trị âm cho discharge

3. **Dashboard:**
   - Cần clamp absolute value trước khi đảo dấu
   - Không được dùng `Math.max(val, 0)` trực tiếp với giá trị âm

---

## 📝 CHECKLIST

- [x] API trả về signed values đúng
- [x] API client giữ nguyên signed trong `battery_series_5min_w`
- [x] Sensor charge lấy giá trị dương
- [x] Sensor discharge lấy giá trị âm (giữ nguyên)
- [x] Dashboard charge clamp đúng
- [x] Dashboard discharge clamp absolute value rồi mới đảo dấu

**Tất cả đã ĐÚNG!** ✅

