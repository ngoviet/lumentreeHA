# KIỂM TRA LOGIC CHARGE/DISCHARGE

## 📊 PHÂN TÍCH LOGIC HIỆN TẠI

### **1. API Response Structure** (`/lesvr/getBatDayData`)

Theo documentation:
```json
{
  "data": {
    "bats": [
      {"tableValue": 290},  // bats[0] = Charge
      {"tableValue": 150}   // bats[1] = Discharge
    ],
    "tableValueInfo": [
      // Positive (+) = Charge (pin nhận năng lượng)
      // Negative (-) = Discharge (pin phát năng lượng)
      500, 500, -200, -300, ...
    ]
  }
}
```

**Quy ước API:**
- `bats[0]` = Charge total
- `bats[1]` = Discharge total
- `tableValueInfo`: **positive = charge, negative = discharge**

---

### **2. API Client Processing** (`api_client.py:616-625`)

```python
# Comment: positive = charge, negative = discharge
series_w = [500, 500, -200, -300, ...]  # Từ API

# Charge: keep positive values
charge_kwh5 = [w if w > 0 else 0.0 for w in series_w]
# → [500, 500, 0, 0, ...] ✅

# Discharge: keep negative values, convert to positive kWh
discharge_kwh5 = [abs(w) if w < 0 else 0.0 for w in series_w]
# → [0, 0, 200, 300, ...] ✅

# Giữ nguyên signed trong battery_series_5min_w
battery_series_5min_w = [500, 500, -200, -300, ...] ✅
```

**Kết quả:**
- `charge_today` = từ `bats[0]` ✅
- `discharge_today` = từ `bats[1]` ✅
- `battery_series_5min_w` = giữ nguyên signed ✅

---

### **3. Sensor Entity** (`sensor.py:976-985`)

```python
battery_series = [500, 500, -200, -300, ...]  # Từ coordinator

# Charge sensor (KEY_DAILY_CHARGE_KWH):
attrs["series_5min_w"] = [w if w > 0 else 0.0 for w in battery_series]
# → [500, 500, 0, 0, ...] ✅ (dương, hiển thị trên 0)

# Discharge sensor (KEY_DAILY_DISCHARGE_KWH):
attrs["series_5min_w"] = [w if w < 0 else 0.0 for w in battery_series]
# → [0, 0, -200, -300, ...] ✅ (âm, hiển thị dưới 0)
```

**Kết quả:**
- Charge sensor: giá trị dương (trên 0) ✅
- Discharge sensor: giá trị âm (dưới 0) ✅

---

### **4. Dashboard** (`dashboard_battery_charge_discharge.yaml`)

```javascript
// Charge series:
// Input: [500, 500, 0, 0, ...] (từ sensor, đã là dương)
return [timestamp.getTime(), Math.min(Math.max(val, 0), 4000)];
// → Hiển thị trên 0 ✅

// Discharge series:
// Input: [0, 0, -200, -300, ...] (từ sensor, đã là âm)
const absVal = Math.abs(val);  // 200, 300
const clamped = Math.min(Math.max(absVal, 0), 3000);  // 200, 300
return [timestamp.getTime(), -clamped];  // -200, -300
// → Hiển thị dưới 0 ✅
```

**Kết quả:**
- Charge: hiển thị trên 0 ✅
- Discharge: hiển thị dưới 0 ✅

---

## ✅ KẾT LUẬN LOGIC HIỆN TẠI

| Bước | Charge | Discharge | Status |
|------|--------|-----------|--------|
| **API** | `bats[0]`, positive values | `bats[1]`, negative values | ✅ |
| **API Client** | Lấy w > 0 | Lấy w < 0, abs() cho kWh | ✅ |
| **Sensor** | Lấy w > 0 (dương) | Lấy w < 0 (âm) | ✅ |
| **Dashboard** | Hiển thị trên 0 | Hiển thị dưới 0 | ✅ |

**Logic hiện tại ĐÚNG theo documentation!**

---

## ⚠️ NẾU VẪN BỊ ĐẢO NGƯỢC

Có thể API thực tế trả về **NGƯỢC LẠI**:
- **Negative = Charge** (pin nhận năng lượng)
- **Positive = Discharge** (pin phát năng lượng)

### **Cách kiểm tra:**

1. **Test API trực tiếp:**
   ```bash
   # Gọi API getBatDayData và xem response
   # Kiểm tra: khi battery đang sạc, tableValueInfo có giá trị dương hay âm?
   ```

2. **So sánh với thực tế:**
   - Khi battery đang **sạc** (charge) → giá trị trong `tableValueInfo` là **dương hay âm**?
   - Khi battery đang **xả** (discharge) → giá trị trong `tableValueInfo` là **dương hay âm**?

3. **Kiểm tra daily totals:**
   - `bats[0]` có phải là charge không?
   - `bats[1]` có phải là discharge không?

---

## 🔧 NẾU CẦN ĐẢO NGƯỢC LOGIC

Nếu API thực tế trả về **negative = charge, positive = discharge**, cần sửa:

### **1. api_client.py:**
```python
# Charge: keep negative values
charge_kwh5 = self._series_5min_kwh([abs(w) if w < 0 else 0.0 for w in series_w])
# Discharge: keep positive values
discharge_kwh5 = self._series_5min_kwh([w if w > 0 else 0.0 for w in series_w])
```

### **2. sensor.py:**
```python
# Charge: keep negative values, convert to positive
attrs["series_5min_w"] = [abs(w) if w < 0 else 0.0 for w in battery_series]
# Discharge: keep positive values, convert to negative
attrs["series_5min_w"] = [-w if w > 0 else 0.0 for w in battery_series]
```

---

## 📝 CHECKLIST KIỂM TRA

- [ ] Test API response thực tế
- [ ] So sánh với trạng thái battery thực tế
- [ ] Kiểm tra daily totals (`bats[0]` vs `bats[1]`)
- [ ] Xác nhận quy ước sign của `tableValueInfo`


