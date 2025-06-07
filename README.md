# LumentreeHA – Home Assistant Custom Integration

## 🌐 Overview

This is a custom integration for connecting Lumentree and SUNT hybrid inverters to Home Assistant.  
It supports real-time monitoring of PV generation, battery status, grid flow, load consumption, and more.

Đây là custom component giúp kết nối biến tần hybrid Lumentree hoặc SUNT với Home Assistant.  
Hỗ trợ giám sát thông số điện năng như công suất PV, pin, lưới, tải tiêu thụ theo thời gian thực.

---

## ⚙️ Supported Devices | Thiết bị hỗ trợ

- SUNT 4.0KW-H Hybrid Inverter
- Lumentree 5.5kW Hybrid Inverter
- Other inverters with similar data structure

---

## ✨ Features | Tính năng chính

- 📡 Auto-discovery via config flow (add by IP + SN)
- ⚡ Realtime sensor updates via polling
- 📊 Lovelace support for power visualization (e.g. mini-graph-card)
- 🔋 Battery SOC, charge/discharge power tracking
- 🔌 Load, PV, grid, and inverter metrics
- 🧮 Custom sensor: `total_load_power = load_power + ac_output_power`

---

## 🆕 Recent Changes | Thay đổi gần đây

### 🇺🇸 English
- ✅ Added `total_load_power` sensor: total = `load_power` + `ac_output_power`
- ✅ Icon support and proper unit (`W`)
- ✅ Lovelace graph integration with `mini-graph-card`

### 🇻🇳 Tiếng Việt
- ✅ Thêm cảm biến `total_load_power`: tổng tải = `load_power` + `ac_output_power`
- ✅ Hỗ trợ biểu tượng và đơn vị `W`
- ✅ Hiển thị biểu đồ trong Lovelace

---

## 🛠️ Installation | Cài đặt

1. Copy folder `lumentree` to `custom_components` in your Home Assistant config directory
2. Restart Home Assistant
3. Go to *Settings → Devices & Services → Add Integration*
4. Choose **LumentreeHA**, then enter IP + SN of inverter

---

## 🖼️ Interface Preview | Giao diện minh hoạ

<table>
  <tr>
    <td align="center"><strong>Lumentree 5.5kW</strong><br><img src="https://github.com/ngoviet/LumentreeHA/blob/main/Lumentree4kw.png" width="400"/></td>
    <td align="center"><strong>SUNT 4.0kW-H</strong><br><img src="https://github.com/ngoviet/LumentreeHA/blob/main/Lumentree5.5kw.png" width="400"/></td>
  </tr>
</table>

---

## 📈 Lovelace Example | Ví dụ biểu đồ Lovelace

```yaml
type: custom:mini-graph-card
name: Tổng công suất tải
icon: mdi:lightning-bolt
entities:
  - entity: sensor.device_h240909079_total_load_power
    name: Total Load Power
line_width: 3
hours_to_show: 24
points_per_hour: 6
```

---

## 📮 Contact & Credit

This fork is customized by [Ngô Đức Việt](https://github.com/ngoviet) for real-world hybrid inverters and dashboard integration.  
Original base: [vboyhn/LumentreeHA](https://github.com/vboyhn/LumentreeHA)

