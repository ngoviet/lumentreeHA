# Lumentree Inverter cho Home Assistant

<!-- readme-axi type=ha -->

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/ngoviet/lumentreeHA.svg)](https://github.com/ngoviet/lumentreeHA/releases)
[![GitHub stars](https://img.shields.io/github/stars/ngoviet/lumentreeHA.svg)](https://github.com/ngoviet/lumentreeHA/stargazers)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?style=flat&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/ngoviet)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-ff69b4?style=flat&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/ngoviet)

[English](README.md) · **Tiếng Việt**

Theo dõi **inverter hybrid năng lượng mặt trời Lumentree** (dòng SUNT) trong Home Assistant: công suất, pin và lưới cập nhật trực tiếp mỗi 5 giây, cùng thống kê điện năng theo ngày, tháng, năm và toàn thời gian, có biểu đồ và số tiền điện tiết kiệm được tính bằng VND.

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=lumentreeHA&category=integration" target="_blank"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Mở repo này trong HACS" width="200" height="36"></a>

> 🇻🇳 Dự án do một người Việt tự xây dựng và duy trì — nếu nó giúp ích cho bạn, hãy
> [ủng hộ dự án](#ủng-hộ-dự-án).

| Sensor | Biểu đồ điện năng 24 giờ | Tóm tắt thống kê |
|---|---|---|
| ![Tổng quan sensor](images/sensors_entity_overview.jpg) | ![Biểu đồ điện năng 24 giờ](images/dashboard_energy_charts_24h.jpg) | ![Tóm tắt thống kê](images/dashboard_statistics_summary.jpg) |

## Mục lục

- [Tính năng](#tính-năng)
- [Yêu cầu](#yêu-cầu)
- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Thực thể](#thực-thể)
- [Dịch vụ](#dịch-vụ)
- [Xử lý sự cố](#xử-lý-sự-cố)
- [Cách hoạt động](#cách-hoạt-động)
- [Phát triển](#phát-triển)

## Tính năng

- **Số liệu trực tiếp mỗi 5 giây** qua MQTT: PV (hai string), công suất pin, điện áp, dòng điện và SOC, lưới, tải, AC vào và AC ra, nhiệt độ, và các cell pin.
- **Cài đặt của inverter** đọc từ thiết bị: điện áp và dòng sạc, ngưỡng bảo vệ, chế độ làm việc, AI mode, loại lưới và nhiều thông số khác. Đây là các sensor chẩn đoán, chỉ đọc.
- **Thống kê điện năng** cho hôm nay, tháng này, năm nay và toàn thời gian:
  - điện PV sản xuất
  - pin sạc và xả
  - điện mua từ lưới
  - tải gia đình, tải ưu tiên (essential load) và tổng tải
- **Tiết kiệm**: lượng điện không phải mua từ lưới (kWh) và giá trị quy ra VND, theo đơn giá cố định 2.900 VND/kWh.
- **Thuộc tính sẵn cho biểu đồ**:
  - chuỗi số liệu 5 phút và theo giờ cho hôm nay
  - mỗi ngày một giá trị cho tháng
  - mỗi tháng một giá trị cho năm
- **Bù lịch sử (backfill)**: lần chạy đầu, integration nạp tới 5 năm dữ liệu cũ và lưu lại trên đĩa.
- **Nhiều inverter**: mỗi inverter thêm một config entry.
- **Chỉ đọc**: integration không bao giờ thay đổi cài đặt inverter và không gọi endpoint ghi nào của hãng.

## Yêu cầu

| | |
|---|---|
| Home Assistant | **2024.4** trở lên (HACS chặn các bản cũ hơn) |
| Mạng | Ra Internet tới `lesvr.suntcn.com`: cổng **1886** (MQTT) và **80** (HTTP) |
| Inverter | Đang online trên app Lumentree / LightEarth, kèm **Device ID** (vd `H240909079`) |

Các thư viện Python (`paho-mqtt`, `crcmod`) được Home Assistant tự cài.

## Cài đặt

### HACS (khuyên dùng)

1. Bấm nút **Mở trong HACS** ở trên, hoặc trong HACS mở **⋮ → Custom repositories**, thêm `https://github.com/ngoviet/lumentreeHA` với loại **Integration**.
2. Tải **Lumentree Inverter**.
3. Khởi động lại Home Assistant.

### Thủ công

1. Tải [bản phát hành](https://github.com/ngoviet/lumentreeHA/releases) mới nhất.
2. Chép toàn bộ nội dung repo vào `<config>/custom_components/lumentree/`, sao cho `manifest.json` nằm ở `custom_components/lumentree/manifest.json`.
3. Khởi động lại Home Assistant.

### Cập nhật

Khi có bản phát hành mới, HACS hiện nó ở **Cài đặt → Cập nhật** và ngay trong HACS. Cài bản mới rồi **khởi động lại Home Assistant**.

Muốn thấy bản cập nhật ngay, mở repo trong HACS và chọn **⋮ → Update information**.

Ghi chú phát hành, kể cả những thay đổi bạn sẽ thấy sau khi cập nhật, nằm ở [trang Releases](https://github.com/ngoviet/lumentreeHA/releases).

## Cấu hình

1. Vào **Cài đặt → Thiết bị & Dịch vụ → Thêm tích hợp** và tìm **Lumentree Inverter**.
2. Nhập **Device ID**. Mã này in trên nhãn inverter và hiện trong app Lumentree.
3. Xác nhận thiết bị tìm thấy.

Lặp lại cho từng inverter. Muốn đổi Device ID sau này, chọn **Cấu hình lại** (Reconfigure) trên mục integration.

Trong vài phút đầu sau khi cài, integration tải lịch sử của bạn về (xem [Thống kê và lịch sử](#thống-kê-và-lịch-sử)). Số liệu tháng, năm và toàn thời gian sẽ đầy dần khi việc này xong.

## Thực thể

Entity ID theo mẫu `sensor.device_<serial>_<key>`, ví dụ `sensor.device_h240909079_battery_soc`.

### Thời gian thực (MQTT): 55 sensor

| Nhóm | Sensor |
|---|---|
| Công suất | PV, PV1\*, PV2\*, Battery, Grid, Load, Total Load, AC Output, AC Output Apparent Power, AC Input, Generator |
| Điện áp | Battery, PV1\*, PV2\*, Grid, AC Output, AC Input\* |
| Dòng điện | Battery, AC Input, AC Output |
| Tần số | AC Output, AC Input |
| Pin | SOC, Status, Type, Battery Cell Info (điện áp từng cell nằm trong thuộc tính) |
| Trạng thái | Grid Status, Master/Slave, Self-Consumption Ratio, Device Temperature, PV Input Today |
| Cài đặt (chẩn đoán) | Battery Capacity, Max Charge Current, Max Discharge Current, Equalizing / Boost / Float Charge Voltage, Low Voltage Protection, Recovery Voltage, Low Capacity Cutoff, Protecting Recovery Point, Equalizing Charge Interval and Time, CT Trickle Feed, AI Mode, Grid Type, AC Output Frequency Setting, Charge From AC, AC Coupling, Work Mode, Battery Mode |
| Thông tin (chẩn đoán) | Firmware Version, Controller Version, Device SN (MQTT)\*, Last Raw MQTT Hex\* |

\* Tắt sẵn (7 sensor). Cần thì bật trong danh sách entity của thiết bị.

Một số inverter gửi khung MQTT ngắn hơn, khi đó các cài đặt ở vùng thanh ghi phía trên sẽ ở trạng thái `unknown`. Đó là bình thường; xem [thanh ghi có mặt theo độ dài khung](docs/api/REGISTER_MAP.md#frame-layout).

### Thống kê (HTTP): 28 sensor

| Kỳ | Sensor | Thuộc tính cho biểu đồ |
|---|---|---|
| Hôm nay (7) | PV, Charge, Discharge, Grid Input, Load, Essential Load, Total Load | `series_5min_w`, `series_5min_kwh`, `series_hour_kwh`, `saved_kwh`, `savings_vnd` |
| Tháng này (7) | như trên | `daily_pv`, `daily_charge`, …, `daily_saved_kwh`, `daily_savings_vnd` (mỗi ngày một giá trị) |
| Năm nay (7) | như trên | `monthly_pv`, `monthly_charge`, …, `monthly_saved_kwh`, `monthly_savings_vnd` (mỗi tháng một giá trị) |
| Tổng (7) | như trên, toàn thời gian | `years_processed`, `earliest_year`, `latest_year` |

Mọi thống kê làm mới mỗi 5 phút, và **hôm nay được tính vào** số liệu tháng, năm và toàn thời gian. Các sensor "Hôm nay" dùng được trong **Energy dashboard** của Home Assistant.

### Binary sensor: 2

- **Online Status**: chuyển sang tắt khi 12,5 giây không nhận được khung MQTT nào.
- **UPS Mode**

### Thống kê và lịch sử

- **Hôm nay** lấy trực tiếp từ cloud Lumentree mỗi 5 phút.
- **Các ngày đã qua** được lưu trên đĩa ở `<config>/.storage/lumentree_stats/<device>/<year>.json`. Số liệu tháng, năm và toàn thời gian tính từ các tệp này, cộng thêm số liệu trực tiếp của hôm nay.
- **Mỗi lần khởi động**, integration bù phần lịch sử còn thiếu theo từng tháng, tối đa 5 năm về trước. Khởi động lại khi lịch sử đã đủ thì chỉ hỏi cloud tháng hiện tại.
- **Ngay sau nửa đêm** (00:20), integration lưu tổng cuối cùng của hôm qua và bù các chỗ trống.
- Một ngày chỉ được lưu khi đã kết thúc, nên giá trị đọc giữa ngày không bao giờ bị giữ lại.

Không cần cấu hình gì. Nếu lịch sử trông sai, xem [Dịch vụ](#dịch-vụ) để dựng lại.

### Dashboard

Dashboard Lovelace dựng sẵn nằm trong [`docs/dashboard/`](docs/dashboard/):

- [Thống kê theo ngày](docs/dashboard/dashboard_daily_stats.yaml)
- [PV và lưới](docs/dashboard/dashboard_pv_grid.yaml)
- [Tổng tải](docs/dashboard/dashboard_total_load.yaml)
- [Pin sạc và xả](docs/dashboard/dashboard_battery_charge_discharge.yaml)

Hướng dẫn cài ở [DASHBOARD_README.md](docs/dashboard/DASHBOARD_README.md), cách sửa các lỗi biểu đồ thường gặp ở [TROUBLESHOOTING_GUIDE.md](docs/dashboard/TROUBLESHOOTING_GUIDE.md).

## Dịch vụ

Mọi dịch vụ nằm trong domain `lumentree`. Dịch vụ nào cũng nhận tham số tuỳ chọn **`device_sn`**: bỏ trống thì dịch vụ chạy cho mọi inverter đã cấu hình.

| Dịch vụ | Tác dụng |
|---|---|
| `smart_backfill` | Bù lịch sử còn thiếu theo từng tháng (nhanh). Tuỳ chọn: `max_years`, `optimize_cache`. |
| `purge_and_backfill` | Xoá lịch sử đã lưu rồi dựng lại bằng `smart_backfill`. |
| `backfill_all` | Dựng lại lịch sử theo từng ngày (chậm, mỗi ngày một request). Dùng khi `smart_backfill` báo cloud bỏ qua tham số tháng. |
| `backfill_gaps` | Bù các ngày thiếu, giới hạn số ngày mỗi lần chạy. |
| `backfill_now` | Bù N ngày đã qua gần nhất. |
| `backfill_empty_dates` | Kiểm tra lại các ngày đã ghi là rỗng. |
| `recompute_month_year` | Tính lại tổng tháng và năm của năm nay từ các ngày đã lưu. |
| `optimize_cache` | Bỏ các ngày rỗng khỏi tệp đã lưu. |
| `purge_cache` / `purge_all_cache` | Xoá lịch sử của một năm, hoặc toàn bộ. |
| `mark_empty_dates` / `mark_coverage_range` | Sửa tay lịch sử đã lưu. |
| `enable_purge_on_startup` / `disable_purge_on_startup` | Xoá và dựng lại lịch sử ở lần khởi động lại kế tiếp (tự tắt sau đó). |

Ví dụ (dựng lại lịch sử cho một inverter):

```yaml
service: lumentree.purge_and_backfill
data:
  device_sn: H240909079
  max_years: 5
```

## Xử lý sự cố

**Cài đặt thất bại hoặc cứ thử lại mãi.** Kiểm tra Home Assistant có kết nối được `lesvr.suntcn.com` ở cổng 80 và 1886 không. Nếu cloud hoặc broker đang sập, Home Assistant sẽ tự thử cài lại.

**Sensor trực tiếp ngừng cập nhật.** Xem **Online Status**. Integration tự kết nối lại MQTT với độ trễ tăng dần. Nếu chính inverter đang offline trên app Lumentree thì sẽ không có dữ liệu nào tới.

**Thống kê hiện `unavailable`.** Cloud Lumentree không trả lời request gần nhất. Sensor sẽ trở lại ở lần làm mới thành công kế tiếp, trong vòng 5 phút.

**Số liệu tháng / năm / toàn thời gian thấp bất thường.** Lịch sử có thể vẫn đang tải sau lần chạy đầu. Chờ vài phút, hoặc chạy `lumentree.smart_backfill`.

**Bật log debug:**

```yaml
logger:
  logs:
    custom_components.lumentree: debug
```

Khi báo lỗi, đính kèm **Tải xuống chẩn đoán** (Download diagnostics) từ trang thiết bị (token đã được che) và log debug. Dùng [trang issue](https://github.com/ngoviet/lumentreeHA/issues).

## Cách hoạt động

```
Inverter ──► Lumentree cloud ──┬── MQTT  reportApp/<serial>  ──► live sensors (5 s)
                               │   (Modbus-RTU frames; the integration
                               │    publishes read requests to listenApp/<serial>)
                               └── HTTP  lesvr.suntcn.com     ──► statistics (5 min)
                                                                  + history on disk
```

Sơ đồ: inverter gửi lên cloud Lumentree; integration nhận khung Modbus-RTU qua MQTT (`reportApp/<serial>`, gửi yêu cầu đọc vào `listenApp/<serial>`) cho sensor trực tiếp mỗi 5 giây, và gọi HTTP `lesvr.suntcn.com` cho thống kê mỗi 5 phút, kèm lịch sử lưu trên đĩa.

Chi tiết giao thức và thanh ghi cho người đóng góp nằm trong [`docs/`](docs/README.md):

- [Giao thức API](docs/api/API_PROTOCOL.md)
- [Bản đồ thanh ghi](docs/api/REGISTER_MAP.md)
- [Cache và backfill](docs/api/CACHE_AND_BACKFILL.md)
- [Ghi chú phát triển](docs/DEVELOPMENT_NOTES.md)

## Phát triển

Muốn đóng góp, xem [CONTRIBUTING.md](CONTRIBUTING.md). Chạy test bằng `pytest tests/`, lint bằng `ruff check .`.

<!-- support:start -->
## Ủng hộ dự án

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/banner.svg" width="720" alt="Built and maintained by one person in Việt Nam">
</p>

<p align="center">
  <a href="https://buymeacoffee.com/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-coffee.svg" height="56" alt="Buy me a coffee"></a>
  &nbsp;
  <a href="https://github.com/sponsors/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-sponsors.svg" height="56" alt="GitHub Sponsors"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/vietqr-card.svg" width="300" alt="VietQR — MB Bank — NGO DUC VIET — 911051212">
</p>

<p align="center"><sub>🇻🇳 VietQR: quét bằng app ngân hàng bất kỳ, nội dung <code>Ung ho lumentreeHA</code>. Cảm ơn bạn đã giúp dự án tiếp tục phát triển!</sub></p>
<p align="center"><sub>Tiền mã hoá (mạng BEP20): <code>0x57f07d44fb581cddc028a0c67d63a8cc05aa6caa</code> · USDT · USDC · BNB · ETH · BTC</sub></p>
<!-- support:end -->

## Giấy phép

[MIT](LICENSE) © Ngô Đức Việt. Không liên kết với Lumentree hay SUNTCN.
