# Dashboard: Battery Charge & Discharge - Documentation

## Tổng Quan

Dashboard này hiển thị biểu đồ nạp (charge) và xả (discharge) pin với độ phân giải 5 phút, kết hợp dữ liệu historical từ API và real-time từ MQTT.

## Cấu Trúc File

- **File chính**: `dashboard_battery_charge_discharge_debug.yaml`
- **File production**: `dashboard_battery_charge_discharge.yaml` (không có debug section)

## Logic Data Flow

### 1. API Response (HTTP API)
```
Endpoint: /lesvr/getBatDayData?deviceId={id}&queryDate={date}

Response:
{
  "data": {
    "bats": [
      {"tableValue": 290},  // Charge total (0.1 kWh units)
      {"tableValue": 150}   // Discharge total (0.1 kWh units)
    ],
    "tableValueInfo": [
      // 288 giá trị signed (5 phút/lần)
      // API quy ước: positive = discharge, negative = charge
      500, 500, -200, -300, ...
    ]
  }
}
```

### 2. API Client Processing (`api_client.py:616-638`)
```python
# API trả về: positive = discharge, negative = charge
series_w = [500, 500, -200, -300, ...]  # Từ API

# Invert signs để chuẩn hóa
inverted_series_w = [-w for w in series_w]
# → [-500, -500, 200, 300, ...]
# Sau khi invert: positive = charge, negative = discharge

# Lưu vào coordinator data
result["battery_series_5min_w"] = inverted_series_w
```

### 3. Sensor Entity Processing (`sensor.py:973-992`)
```python
# Charge sensor (KEY_DAILY_CHARGE_KWH):
battery_series = [-500, -500, 200, 300, ...]  # Từ coordinator
attrs["series_5min_w"] = [w if w > 0 else 0.0 for w in battery_series]
# → [0, 0, 200, 300, ...]  # Chỉ lấy positive (charge)

# Discharge sensor (KEY_DAILY_DISCHARGE_KWH):
attrs["series_5min_w"] = [w if w < 0 else 0.0 for w in battery_series]
# → [-500, -500, 0, 0, ...]  # Chỉ lấy negative (discharge)
```

### 4. Dashboard Display
```javascript
// Charge series: Nhận positive values → hiển thị trên 0
// Discharge series: Nhận negative values → hiển thị dưới 0
```

## Entity ID Format

Tất cả entity IDs theo format: `sensor.device_{device_sn}_{key}`

**Ví dụ với device_sn = `h240909079`:**
- Charge: `sensor.device_h240909079_charge_today`
- Discharge: `sensor.device_h240909079_discharge_today`
- Battery Power (real-time): `sensor.device_h240909079_battery_power`
- Battery Status (real-time): `sensor.device_h240909079_battery_status`

## Cách Sử Dụng

### Bước 1: Tìm Device SN
1. Vào **Settings** → **Devices & Services** → **Lumentree Inverter**
2. Click vào integration entry
3. Tìm **Device SN** (ví dụ: `h240909079`)

### Bước 2: Thay Device ID trong Dashboard
1. Mở file `dashboard_battery_charge_discharge_debug.yaml`
2. Tìm và thay tất cả `YOUR_DEVICE_ID` bằng device_sn của bạn
3. Ví dụ: `sensor.device_YOUR_DEVICE_ID_charge_today` → `sensor.device_h240909079_charge_today`

### Bước 3: Import vào Home Assistant
1. Vào **Dashboard Editor**
2. Thêm card mới, chọn **Manual**
3. Copy toàn bộ nội dung YAML và paste
4. Save

## Data Generator Logic

### Charge Series
- **Input**: `series_5min_w` attribute từ charge sensor (positive values)
- **Processing**: 
  - Parse string hoặc array
  - Convert mỗi index thành timestamp (5 phút intervals)
  - Clamp values trong range 0-4000W
- **Real-time**: Thêm point từ `battery_power` nếu status = "Charging"
- **Output**: Array of `[timestamp, power]` với power >= 0

### Discharge Series
- **Input**: `series_5min_w` attribute từ discharge sensor (negative values)
- **Processing**:
  - Parse string hoặc array
  - Convert mỗi index thành timestamp (5 phút intervals)
  - Clamp values trong range -3000W to 0
- **Real-time**: Thêm point từ `battery_power` nếu status = "Discharging" (invert thành negative)
- **Output**: Array of `[timestamp, power]` với power <= 0

## Timestamp Calculation

Mỗi index trong `series_5min_w` đại diện cho một interval 5 phút bắt đầu từ 00:00:

```javascript
// Formula
const hours = Math.floor(index / 12);      // 0-23
const minutes = (index % 12) * 5;          // 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55

// Examples
index 0   → 00:00
index 1   → 00:05
index 12  → 01:00
index 143 → 11:55
index 287 → 23:55
```

## Real-time Data Integration

Dashboard tự động kết hợp real-time data từ MQTT sensors:

1. **Check availability**: Verify `battery_power` và `battery_status` entities exist và available
2. **Status check**: 
   - Charge: `battery_status === 'Charging'` → add positive value
   - Discharge: `battery_status === 'Discharging'` → add negative value
3. **Time check**: Chỉ add nếu current time > last historical data point (tránh duplicate)
4. **Clamp values**: Charge (0-4000W), Discharge (-3000W to 0)

## Troubleshooting

### Chart không hiển thị data
1. **Check entities exist**: Verify entity IDs đúng với device_sn của bạn
2. **Check attributes**: Vào Developer Tools → States, tìm entity và check `series_5min_w` attribute
3. **Check data format**: `series_5min_w` có thể là string (comma-separated) hoặc array
4. **Check coordinator**: Verify daily coordinator đang update đúng (check logs)

### Real-time point không hiển thị
1. **Check MQTT sensors**: Verify `battery_power` và `battery_status` entities exist
2. **Check status value**: Phải là exact string "Charging" hoặc "Discharging" (case-sensitive)
3. **Check time**: Real-time point chỉ add nếu current time > last historical point

### Values hiển thị sai
1. **Check API inversion**: Verify `api_client.py` đang invert signs đúng
2. **Check sensor filtering**: Verify sensor đang filter charge (positive) và discharge (negative) đúng
3. **Check dashboard logic**: Verify data_generator đang parse và process đúng

## Best Practices

1. **Device ID**: Luôn dùng placeholder `YOUR_DEVICE_ID` trong template files
2. **Comments**: Thêm comments giải thích logic phức tạp
3. **Error handling**: Graceful degradation nếu entities không tồn tại
4. **Validation**: Validate data format (string vs array) trước khi process
5. **Clamping**: Luôn clamp values trong reasonable range để tránh outliers
6. **Time handling**: Luôn check time trước khi add real-time points

## Related Files

- `core/api_client.py`: API client processing (inversion logic)
- `entities/sensor.py`: Sensor entity (attribute generation)
- `coordinators/daily_coordinator.py`: Daily stats coordinator
- `CHARGE_DISCHARGE_CHECK.md`: Detailed logic analysis
- `BATTERY_CHARGE_DISCHARGE_FLOW_ANALYSIS.md`: Complete flow documentation

