# Dashboard Configuration - Lumentree Integration

File này chứa các dashboard configuration cho Lumentree Integration.

## Files Dashboard

### 1. `dashboard_total_load.yaml`
Dashboard chart cho biểu đồ tiêu thụ tổng (Total Load) với độ phân giải 5 phút/lần.

### 2. `dashboard_pv_grid.yaml`
Dashboard chart kết hợp cho cả PV Production và Grid Import trên cùng một biểu đồ (5 phút/lần).

### 3. `dashboard_daily_stats.yaml`
Dashboard stats card hiển thị 7 chỉ số daily với mushroom-chips-card: PV, Grid, Load, Essential, Total Load, Charge, Discharge.

**Cách sử dụng chung:**
1. Copy nội dung file dashboard YAML bạn muốn sử dụng
2. Trong Home Assistant, vào Dashboard editor
3. Thêm card mới, chọn "Manual" và paste YAML
4. **Lưu ý**: 
   - `dashboard_total_load.yaml`: Đã có sẵn device_sn `YOUR_DEVICE_ID`
   - `dashboard_pv_grid.yaml`: Đã có sẵn device_sn `YOUR_DEVICE_ID`
   - `dashboard_daily_stats.yaml`: Đã có sẵn device_sn `YOUR_DEVICE_ID`
   - Nếu device_sn khác, thay `YOUR_DEVICE_ID` trong entity IDs

**Ví dụ đầy đủ:**
```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      # ⚡ Tiêu thụ tổng hôm nay (Total Load - 5 phút/lần)
  - type: custom:apexcharts-card
    header:
      title: Tiêu thụ
      show: true
    graph_span: 24h
    span:
      start: day
    now:
      show: false
    apex_config:
      chart:
        type: area
        height: 300
      xaxis:
        type: datetime
        labels:
          format: HH:mm
          rotate: -45
      yaxis:
        - title:
            text: Watt
          min: 0
    series:
      - entity: sensor.device_YOUR_DEVICE_ID_total_load_today
        name: Consumption (W)
        type: area
        color: "#4169E1"
        stroke_width: 2
        data_generator: |
          return (function() {
            const series = entity.attributes.series_5min_w || [];
            const now = new Date();
            const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
            
            return series.map(function(value, index) {
              const hours = Math.floor(index / 12);
              const minutes = (index % 12) * 5;
              const timestamp = new Date(startOfDay);
              timestamp.setHours(hours, minutes, 0, 0);
              return [timestamp.getTime(), parseFloat(value) || 0];
            });
          })();
```

## Chi tiết kỹ thuật

### Data Source
- **Entity**: `sensor.device_{device_sn}_total_load_today`
- **Attribute**: `series_5min_w` (array of 288 floats)
- **Data points**: 288 điểm (24 giờ × 12 điểm/giờ)
- **Interval**: 5 phút/lần

### Visualization
- **Chart type**: Area chart
- **Color**: Blue (#4169E1)
- **Time range**: 24 hours (00:00 - 23:55)
- **Y-axis**: Auto-scaling, min = 0, unit = Watt

### Tùy chỉnh

**Thay đổi màu sắc:**
```yaml
color: "#FF5733"  # Màu đỏ cam
color: "#32CD32"  # Màu xanh lá
```

**Thay đổi time range (ví dụ: chỉ hiển thị 5:00 - 19:00):**
```javascript
data_generator: |
  return (function() {
    const series = entity.attributes.series_5min_w || [];
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    
    // Filter từ 5:00 (index 60) đến 19:00 (index 228)
    const startIndex = 60; // 5 giờ * 12 points/giờ = 60
    const endIndex = 228;  // 19 giờ * 12 points/giờ = 228
    
    return series.slice(startIndex, endIndex + 1).map(function(value, index) {
      const actualIndex = startIndex + index;
      const hours = Math.floor(actualIndex / 12);
      const minutes = (actualIndex % 12) * 5;
      const timestamp = new Date(startOfDay);
      timestamp.setHours(hours, minutes, 0, 0);
      return [timestamp.getTime(), parseFloat(value) || 0];
    });
  })();
```

**Thay đổi chart height:**
```yaml
apex_config:
  chart:
    type: area
    height: 400  # Tăng chiều cao
```

## Yêu cầu

- Home Assistant với custom component `apexcharts-card` đã được cài đặt
- Entity `sensor.device_{device_sn}_total_load_today` phải có attribute `series_5min_w`
- Daily Stats Coordinator phải đang chạy và update data

## Troubleshooting

### Chart không hiển thị data
1. Kiểm tra entity ID có đúng không (thay `{{device_sn}}`)
2. Kiểm tra entity có attribute `series_5min_w` không:
   ```yaml
   - type: entity
     entity: sensor.device_YOUR_DEVICE_ID_total_load_today
     attribute: series_5min_w
   ```
3. Kiểm tra Daily Stats Coordinator có đang chạy không
4. Xem logs để kiểm tra errors

### Data không update
- Daily Stats Coordinator update mỗi 5 phút (default)
- Kiểm tra `last_update` của entity
- Restart Home Assistant nếu cần

### Chart hiển thị sai time
- Kiểm tra timezone của Home Assistant
- Đảm bảo `startOfDay` được tính đúng với timezone hiện tại

---

### 2. Dashboard PV & Grid (Combined Chart)

**Cách sử dụng:**
1. Copy nội dung file `dashboard_pv_grid.yaml`
2. Trong Home Assistant, vào Dashboard editor
3. Thêm card mới, chọn "Manual" và paste YAML
4. Đã có sẵn device_sn `YOUR_DEVICE_ID`, không cần thay đổi

**Ví dụ đầy đủ:**
```yaml
type: vertical-stack
cards:
  - type: markdown
    content: |
      # ⚡ Sản lượng PV và Grid hôm nay (5 phút/lần)
  - type: custom:apexcharts-card
    header:
      title: PV Production & Grid Import
      show: true
    graph_span: 24h
    series:
      - entity: sensor.device_YOUR_DEVICE_ID_pv_today
        name: PV Production (W)
        type: area
        color: "#FFD700"
      - entity: sensor.device_YOUR_DEVICE_ID_grid_in_today
        name: Grid Import (W)
        type: area
        color: "#32CD32"
```

**Chi tiết:**
- **2 series trong cùng một chart**: PV và Grid
- **Màu sắc**:
  - PV: Vàng (#FFD700)
  - Grid: Xanh lá (#32CD32)
- **Data source**: 
  - PV: `series_5min_w` từ `sensor.device_YOUR_DEVICE_ID_pv_today`
  - Grid: `series_5min_w` từ `sensor.device_YOUR_DEVICE_ID_grid_in_today`
- **Use case**: So sánh sản lượng PV với lượng điện nhập từ lưới

---

### 3. Dashboard Daily Stats (Mushroom Chips Card)

**Cách sử dụng:**
1. Copy nội dung file `dashboard_daily_stats.yaml`
2. Trong Home Assistant, vào Dashboard editor
3. Thêm card mới, chọn "Manual" và paste YAML
4. Đã có sẵn device_sn `YOUR_DEVICE_ID`, không cần thay đổi

**Yêu cầu:**
- Cần cài đặt custom cards:
  - [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom)
  - [Stack In Card](https://github.com/custom-cards/stack-in-card)

**7 chỉ số hiển thị:**
1. **PV Production** - Màu amber khi > 0, icon mdi:solar-power
2. **Grid Import** - Màu blue khi > 0, icon mdi:transmission-tower-import
3. **Load** - Màu orange khi > 0, icon mdi:home-lightning-bolt
4. **Essential** - Màu purple khi > 0, icon mdi:power-plug
5. **Total Load** - Màu red khi > 0, icon mdi:lightning-bolt-circle
6. **Battery Charge** - Màu green khi > 0, icon mdi:battery-plus-variant
7. **Battery Discharge** - Màu teal khi > 0, icon mdi:battery-minus-variant

**Tính năng:**
- Hiển thị giá trị rounded 2 chữ số thập phân với unit "kWh"
- Màu sắc động: colored khi giá trị > 0, grey khi = 0
- Tap vào chip để mở more-info dialog của entity
- Auto-update khi daily coordinator cập nhật data

**Ví dụ đầy đủ:**
```yaml
type: custom:stack-in-card
cards:
  - type: custom:mushroom-chips-card
    chips:
      - type: template
        icon: mdi:solar-power
        icon_color: "{{ 'amber' if pv > 0 else 'grey' }}"
        content: PV {{ pv|round(2) }} kWh
        tap_action:
          action: more-info
          entity: sensor.device_YOUR_DEVICE_ID_pv_today
```

---

*For more information, see DEVELOPMENT_LOG.md*

