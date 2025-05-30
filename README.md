# 🔌 LumentreeHA

Kết nối biến tần năng lượng mặt trời **Lumentree** với **Home Assistant** – cho phép giám sát, điều khiển và mở rộng khả năng tích hợp hệ thống điện mặt trời vào hệ sinh thái smarthome.

<table>
  <tr>
    <td align="center"><strong>Lumentree 5.5kW</strong><br><img src="https://github.com/ngoviet/LumentreeHA/blob/main/sensor.png" width="400"/></td>
    <td align="center"><strong>Lumentree 4kw</strong><br><img src="https://github.com/ngoviet/LumentreeHA/blob/main/Lumentree4kw.png" width="400"/></td>
  </tr>
</table>



---

## 🛠️ Các thay đổi trong bản chỉnh sửa này (so với repo gốc `vboyhn/LumentreeHA`)

> Đây là bản fork từ [vboyhn/LumentreeHA](https://github.com/vboyhn/LumentreeHA), được chỉnh sửa và mở rộng:

- ✅ **Fix lỗi thread-unsafe**: thay thế `async_dispatcher_send` bằng `dispatcher_send` để tương thích Home Assistant mới.
- ✅ **Sửa lỗi reconnect gây crash**: xử lý `hass.async_create_task()` đúng thread context.
- ✅ **Cải tiến log**: thêm debug rõ ràng hơn khi kết nối thất bại hoặc mất phiên.
- ✅ **Tối ưu tương thích** với Home Assistant 2024.x.
- 🔄 Có thể sẽ cập nhật thêm hỗ trợ kết nối trực tiếp với ESP32 trong tương lai.

---

## 🚀 Cách sử dụng

### ENGLISH:
- Copy the `lumentree` folder into your `custom_components` directory.
- Reboot Home Assistant.
- Add new integration: **Lumentree**.
- Enter your Device ID (serial number) to log in and start syncing data.

### TIẾNG VIỆT:
- Sao chép thư mục `lumentree` vào `custom_components` trong Home Assistant.
- Khởi động lại Home Assistant.
- Vào phần `Cấu hình > Tích hợp (Integrations)` để thêm thiết bị **Lumentree**.
- Nhập **số serial (Device ID)** để kết nối và theo dõi dữ liệu từ biến tần.

---

## 📄 License
Giữ nguyên theo [Giấy phép gốc từ vboyhn](https://github.com/vboyhn/LumentreeHA). Các bản chỉnh sửa tuân thủ MIT License.
=======
# LumentreeHA
Connect Lumentree solar inverter to Home Asstistant

<img src="https://github.com/vboyhn/LumentreeHA/blob/main/sensor.png" width="850" alt="Sensor" /> 


# How to use: 
 - Copy 'lumentree' folder to your 'custom_components' folder
 - Reboot your HA
 - Add device lumentree, use Device ID (SN) to login.

  
# Cách sử dụng:
- Sao chép thư mục 'lumentree' vào trong thư mục 'custom_components' của bạn
- Khởi động lại HA của bạn
- Thêm thiết bị lumentree, sử dụng số seri để đăng nhập.


# Future
- Make change setting avaiable.
- Use ESP32 to read and setting your Inverter in local (no need connect to Lumentree server, no need internet)
- ...

# Tương lai
- Thực hiện thay đổi cài đặt biến tần bằng HA.
- Sử dụng ESP32 để đọc và cài đặt Biến tần (không cần kết nối với máy chủ Lumentree, không cần internet)
- ...

* Bạn nào có hứng thú thì cùng nghiên cứu với mình nhé!!!
>>>>>>> 8ace0c8c41cfd2fa6107be635857d4bd2c1cd2b7
