# Báo Cáo Tương Thích: sunsynk_power_flow_card.yaml

## Tổng Quan
File dashboard `sunsynk_power_flow_card.yaml` có **một số vấn đề tương thích** với backend Lumentree integration.

## Format Entity ID Đúng Của Backend

Backend Lumentree tạo entity IDs theo format:
- **Sensor**: `sensor.device_{device_sn}_{key}`
- **Binary Sensor**: `binary_sensor.device_{device_sn}_{key}`

Ví dụ với device_sn = `h240909079`:
- `sensor.device_h240909079_pv_power`
- `sensor.device_h240909079_total_load_power`
- `binary_sensor.device_h240909079_online_status`

## Phân Tích Entity IDs Trong Dashboard

### ✅ Entity IDs ĐÚNG Format (Tương Thích)

| Entity ID trong Dashboard | Key | Trạng Thái |
|---------------------------|-----|------------|
| `sensor.device_h240909079_pv1_voltage` | `pv1_voltage` | ✅ Đúng |
| `sensor.device_h240909079_pv_today` | `pv_today` | ✅ Đúng |
| `sensor.device_h240909079_grid_power` | `grid_power` | ✅ Đúng |
| `sensor.device_h240909079_grid_voltage` | `grid_voltage` | ✅ Đúng |
| `binary_sensor.device_h240909079_online_status` | `online_status` | ✅ Đúng |
| `sensor.device_h240909079_grid_in_today` | `grid_in_today` | ✅ Đúng |
| `sensor.device_h240909079_battery_voltage` | `battery_voltage` | ✅ Đúng |
| `sensor.device_h240909079_battery_soc` | `battery_soc` | ✅ Đúng |
| `sensor.device_h240909079_battery_current` | `battery_current` | ✅ Đúng |
| `sensor.device_h240909079_battery_power` | `battery_power` | ✅ Đúng |
| `sensor.device_h240909079_charge_today` | `charge_today` | ✅ Đúng |
| `sensor.device_h240909079_discharge_today` | `discharge_today` | ✅ Đúng |
| `sensor.device_h240909079_load_power` | `load_power` | ✅ Đúng |
| `sensor.device_h240909079_ac_output_power` | `ac_output_power` | ✅ Đúng |
| `sensor.device_h240909079_load_today` | `load_today` | ✅ Đúng |
| `sensor.device_h240909079_device_temperature` | `device_temperature` | ✅ Đúng |

### ❌ Entity IDs SAI Format (Không Tương Thích)

| Entity ID trong Dashboard | Vấn Đề | Entity ID Đúng |
|---------------------------|--------|----------------|
| `sensor.sunt_4_0kw_h_pv_power` | ❌ Thiếu prefix `device_` | `sensor.device_h240909079_pv_power` |
| `sensor.sunt_4_0kw_h_total_load_power` | ❌ Thiếu prefix `device_` | `sensor.device_h240909079_total_load_power` |

### ⚠️ Entity IDs Không Phải Từ Lumentree Backend

| Entity ID trong Dashboard | Nguồn | Ghi Chú |
|---------------------------|-------|---------|
| `sensor.sunt_pv_energy_kwh` | ❓ Không rõ | Có thể từ integration khác |
| `sensor.jk_mosfet_temperature` | ❓ Không rõ | Có thể từ JK BMS integration |
| `sensor.hoa_luoi` | ❓ Không rõ | Có thể từ integration khác |

## Các Sensor Keys Có Sẵn Trong Backend

### Realtime Sensors (MQTT)
- `pv_power` → `sensor.device_{device_sn}_pv_power`
- `battery_power` → `sensor.device_{device_sn}_battery_power`
- `grid_power` → `sensor.device_{device_sn}_grid_power`
- `load_power` → `sensor.device_{device_sn}_load_power`
- `total_load_power` → `sensor.device_{device_sn}_total_load_power`
- `pv1_voltage`, `pv1_power`, `pv2_voltage`, `pv2_power`
- `battery_voltage`, `battery_current`, `battery_soc`
- `grid_voltage`, `ac_output_voltage`, `ac_input_voltage`
- `ac_output_power`, `ac_input_power`
- `device_temperature`
- Và nhiều sensors khác...

### Daily Statistics Sensors
- `pv_today` → `sensor.device_{device_sn}_pv_today`
- `charge_today` → `sensor.device_{device_sn}_charge_today`
- `discharge_today` → `sensor.device_{device_sn}_discharge_today`
- `grid_in_today` → `sensor.device_{device_sn}_grid_in_today`
- `load_today` → `sensor.device_{device_sn}_load_today`
- `total_load_today` → `sensor.device_{device_sn}_total_load_today`

### Binary Sensors
- `online_status` → `binary_sensor.device_{device_sn}_online_status`
- `is_ups_mode` → `binary_sensor.device_{device_sn}_is_ups_mode`

## Khuyến Nghị Sửa Lỗi

### 1. Sửa Entity IDs Sai Format

**Thay đổi:**
```yaml
# SAI
pv1_power_186: sensor.sunt_4_0kw_h_pv_power
inverter_power_175: sensor.sunt_4_0kw_h_total_load_power
essential_power: sensor.sunt_4_0kw_h_total_load_power

# ĐÚNG
pv1_power_186: sensor.device_h240909079_pv_power
inverter_power_175: sensor.device_h240909079_total_load_power
essential_power: sensor.device_h240909079_total_load_power
```

### 2. Xác Nhận Entity IDs Từ Integration Khác

Các entity IDs sau không phải từ Lumentree backend:
- `sensor.sunt_pv_energy_kwh`
- `sensor.jk_mosfet_temperature`
- `sensor.hoa_luoi`

**Hành động:**
- Nếu các sensors này tồn tại từ integration khác → Giữ nguyên
- Nếu không tồn tại → Xóa hoặc thay thế bằng sensors từ Lumentree

### 3. Lưu Ý Về Device SN

Dashboard hiện đang hardcode `h240909079`. Nếu muốn dashboard linh hoạt hơn:
- Sử dụng template: `sensor.device_{{ device_sn }}_pv_power`
- Hoặc tạo dashboard riêng cho mỗi device

## Kết Luận

**Tỷ lệ tương thích:** ~70%

**Vấn đề chính:**
1. ❌ 2 entity IDs sai format (thiếu prefix `device_`)
2. ⚠️ 3 entity IDs không phải từ Lumentree backend

**Hành động cần thiết:**
1. Sửa 2 entity IDs sai format
2. Xác nhận và xử lý 3 entity IDs từ integration khác
3. Sau khi sửa, dashboard sẽ tương thích 100% với backend Lumentree

