# ✅ XÁC MINH FLOW: Battery Charge & Discharge

## 🔍 TRACE TOÀN BỘ FLOW

### **BƯỚC 1: API Response**

**Endpoint:** `/lesvr/getBatDayData?deviceId={id}&queryDate={date}`

**Response:**
```json
{
  "returnValue": 1,
  "data": {
    "bats": [
      {"tableValue": 290},  // Charge: 29.0 kWh (290 * 0.1)
      {"tableValue": 150}   // Discharge: 15.0 kWh (150 * 0.1)
    ],
    "tableValueInfo": [
      // 288 giá trị signed (5 phút/lần)
      // Positive = Charge, Negative = Discharge
      500, 500, 450,    // Charge (dương)
      -200, -300, -400, // Discharge (âm)
      0, 0, 0,          // Không hoạt động
      ...
    ]
  }
}
```

---

### **BƯỚC 2: API Client** (`api_client.py`)

**Method:** `_fetch_battery_data()` (dòng 594-639)

#### 2.1. Daily totals:
```python
# Dòng 611-614
result["charge_today"] = float(bats_data[0]["tableValue"]) / 10.0  # 290 → 29.0 kWh ✅
result["discharge_today"] = float(bats_data[1]["tableValue"]) / 10.0  # 150 → 15.0 kWh ✅
```

#### 2.2. Series 5 phút:
```python
# Dòng 618-631
series_w = self._to_float_list(data.get("tableValueInfo"))  # [500, 500, -200, -300, ...]

# Charge: lấy giá trị dương, convert sang kWh
charge_kwh5 = self._series_5min_kwh([w if w > 0 else 0.0 for w in series_w])
# → [500, 500, 0, 0, ...] → convert sang kWh ✅

# Discharge: lấy giá trị âm, dùng abs() để convert sang kWh (vì kWh phải dương)
discharge_kwh5 = self._series_5min_kwh([abs(w) if w < 0 else 0.0 for w in series_w])
# → [0, 0, 200, 300, ...] → convert sang kWh ✅

result.update({
    "battery_series_5min_w": series_w,  # ← GIỮ NGUYÊN SIGNED: [500, 500, -200, -300, ...] ✅
    "battery_charge_series_hour_kwh": [...],
    "battery_discharge_series_hour_kwh": [...],
})
```

**Kết quả:**
```python
{
    "charge_today": 29.0,  # kWh (dương) ✅
    "discharge_today": 15.0,  # kWh (dương) ✅
    "battery_series_5min_w": [500, 500, -200, -300, 0, ...],  # Signed W ✅
}
```

---

### **BƯỚC 3: Merge Results** (`_merge_stats_results()`)

**Method:** `_merge_stats_results()` (dòng 749+)

Merge 3 results từ PV, Battery, Other APIs:
- `charge_today` và `discharge_today` được giữ nguyên
- `battery_series_5min_w` được giữ nguyên

✅ **ĐÚNG** - Không có xử lý thêm

---

### **BƯỚC 4: Coordinator** (`daily_coordinator.py`)

**Method:** `_async_update_data()` (dòng 45-73)

```python
new_data = await self.api.get_daily_stats(self.device_sn, today_str)
return new_data
```

✅ **ĐÚNG** - Chỉ pass through data

**Coordinator data:**
```python
{
    "charge_today": 29.0,
    "discharge_today": 15.0,
    "battery_series_5min_w": [500, 500, -200, -300, ...],
    ...
}
```

---

### **BƯỚC 5: Sensor Entity** (`sensor.py`)

**Class:** `LumentreeDailyStatsSensor`

#### 5.1. Native value (daily total):
```python
# Dòng 909-913
def _update_state_from_coordinator(self):
    key = self.entity_description.key  # "charge_today" hoặc "discharge_today"
    value = self.coordinator.data.get(key)  # 29.0 hoặc 15.0
    self._attr_native_value = round(value, 2) if isinstance(value, (int, float)) else None
```

✅ **ĐÚNG** - Lấy trực tiếp từ coordinator data

#### 5.2. Series 5min_w attribute:
```python
# Dòng 972-991
if key in (KEY_DAILY_CHARGE_KWH, KEY_DAILY_DISCHARGE_KWH):
    battery_series = self.coordinator.data.get("battery_series_5min_w")
    # battery_series = [500, 500, -200, -300, 0, ...]
    
    if key == KEY_DAILY_CHARGE_KWH:
        # Charge: lấy giá trị dương
        attrs["series_5min_w"] = [w if w > 0 else 0.0 for w in battery_series]
        # → [500, 500, 0, 0, 0, ...] ✅
    else:  # discharge
        # Discharge: lấy giá trị âm (GIỮ NGUYÊN, không đảo dấu)
        attrs["series_5min_w"] = [w if w < 0 else 0.0 for w in battery_series]
        # → [0, 0, -200, -300, 0, ...] ✅
```

✅ **ĐÚNG** - Charge lấy dương, Discharge giữ nguyên âm

---

### **BƯỚC 6: Dashboard** (`dashboard_battery_charge_discharge.yaml`)

#### 6.1. Charge series:
```javascript
// Dòng 65-80
const val = parseFloat(value) || 0;  // 500
return [timestamp.getTime(), Math.min(Math.max(val, 0), 4000)];  // [..., 500] ✅
```

✅ **ĐÚNG** - Clamp 0-4000W, hiển thị trên 0

#### 6.2. Discharge series (SAU KHI SỬA):
```javascript
// Dòng 87-106
const val = parseFloat(value) || 0;  // -200 (từ sensor, đã là âm)
const absVal = Math.abs(val);  // 200
const clamped = Math.min(Math.max(absVal, 0), 3000);  // 200
return [timestamp.getTime(), -clamped];  // [..., -200] ✅
```

✅ **ĐÚNG** - Clamp absolute value, giữ dấu âm, hiển thị dưới 0

---

## ✅ KẾT LUẬN

### **Toàn bộ flow đã ĐÚNG:**

| Bước | Charge | Discharge | Status |
|------|--------|-----------|--------|
| **API** | Positive values | Negative values | ✅ |
| **API Client** | `charge_today` (dương) | `discharge_today` (dương) | ✅ |
| **Series W** | Giữ nguyên signed | Giữ nguyên signed | ✅ |
| **Sensor Value** | `charge_today` (29.0 kWh) | `discharge_today` (15.0 kWh) | ✅ |
| **Sensor Series** | `[w if w > 0]` → dương | `[w if w < 0]` → âm | ✅ |
| **Dashboard** | Clamp 0-4000W | Clamp abs, giữ âm | ✅ |

### **Test với dữ liệu thực:**

**Input từ API:**
```json
"tableValueInfo": [500, 500, -200, -300, 0, 100, -150]
```

**Expected output:**

1. **Charge sensor:**
   - Native value: `29.0` kWh ✅
   - `series_5min_w`: `[500, 500, 0, 0, 0, 100, 0]` ✅
   - Dashboard: Hiển thị trên 0 ✅

2. **Discharge sensor:**
   - Native value: `15.0` kWh ✅
   - `series_5min_w`: `[0, 0, -200, -300, 0, 0, -150]` ✅
   - Dashboard: Hiển thị dưới 0 ✅

---

## 🎯 TẤT CẢ ĐÃ ĐÚNG!

Flow xử lý từ API đến dashboard đã hoàn chỉnh và chính xác. Các thay đổi đã được áp dụng đúng cách.

