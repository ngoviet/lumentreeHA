# 🔧 HƯỚNG DẪN NHANH: Add lại Lumentree Integration

## ⚠️ Tình huống: Đã xóa nhầm và không tìm thấy integration

### ✅ Giải pháp nhanh nhất: Add lại từ UI

#### Bước 1: Mở Home Assistant UI
1. Vào **Settings** (⚙️) ở sidebar bên trái
2. Click **Devices & Services**

#### Bước 2: Add Integration
1. Click nút **"+ ADD INTEGRATION"** (góc dưới bên phải, màu xanh)
2. Trong ô tìm kiếm, gõ: **`lumentree`** hoặc **`Lumentree`**
3. Click vào **"Lumentree Inverter"** khi nó xuất hiện

#### Bước 3: Điền thông tin

Bạn cần các thông tin sau (lấy từ app Lumentree trên điện thoại):

1. **Device ID**: 
   - Ví dụ: `H240909079`
   - Tìm trong app Lumentree → Device Info

2. **Device SN (Serial Number)**:
   - Ví dụ: `01K99JBTP1Q9ERQ1BESFXD700R`
   - Tìm trong app Lumentree → Device Info

3. **HTTP Token**:
   - Token từ app Lumentree để truy cập API
   - Thường lấy từ Settings → API Token trong app

4. **MQTT Broker** (nếu dùng MQTT riêng):
   - Nếu dùng MQTT broker mặc định của HA, để trống
   - Nếu dùng MQTT riêng, điền: Host, Port, Username, Password

#### Bước 4: Submit và kiểm tra
1. Click **Submit** sau khi điền đầy đủ
2. Đợi vài giây để HA setup
3. Kiểm tra:
   - Vào lại **Settings** → **Devices & Services** → **Lumentree**
   - Entry mới sẽ hiển thị với trạng thái "loaded"
   - Số entities: khoảng 58 entities

---

## 🔄 Nếu có backup, khôi phục từ backup

### Chạy script khôi phục:

```powershell
cd "\\192.168.10.15\config\custom_components\lumentree\docs\examples"
.\check_and_restore.ps1
```

Script sẽ:
- Kiểm tra xem có backup không
- Nếu có, hỏi bạn có muốn restore không
- Restore và hướng dẫn restart HA

---

## 📋 Thông tin cần thiết (nếu không nhớ)

Nếu bạn không nhớ thông tin device, có thể tìm trong:

1. **App Lumentree trên điện thoại**:
   - Mở app → Device Info
   - Ghi lại: Device ID, Serial Number, API Token

2. **Logs cũ của Home Assistant** (nếu còn):
   ```powershell
   Get-Content "\\192.168.10.15\config\home-assistant.log.1" | Select-String "H240909079|device_id|device_sn" | Select-Object -First 10
   ```

3. **File configuration.yaml** (nếu có cấu hình YAML cũ):
   ```powershell
   Get-Content "\\192.168.10.15\config\configuration.yaml" | Select-String "lumentree"
   ```

---

## ⚡ Sau khi add lại

1. **Restart Home Assistant** (nếu cần):
   - Settings → System → Restart
   - Hoặc chạy: `.\ha-restart-tools\restart_ha.ps1`

2. **Kiểm tra sensors**:
   - Developer Tools → States
   - Tìm: `sensor.device_h240909079_*` hoặc `sensor.h240909079_*`

3. **Kiểm tra entities**:
   - Settings → Devices & Services → Lumentree
   - Click vào entry → Xem danh sách entities

---

## 🆘 Nếu vẫn không tìm thấy "lumentree" trong danh sách integration

Có thể do:
1. **Integration chưa được scan**: Restart Home Assistant
2. **File bị thiếu**: Kiểm tra thư mục `custom_components/lumentree` có đầy đủ file không
3. **Cache chưa clear**: Xóa cache và restart

**Kiểm tra file integration:**
```powershell
Test-Path "\\192.168.10.15\config\custom_components\lumentree\__init__.py"
Test-Path "\\192.168.10.15\config\custom_components\lumentree\manifest.json"
Test-Path "\\192.168.10.15\config\custom_components\lumentree\config_flow.py"
```

Tất cả phải trả về `True`.

---

## 📞 Cần hỗ trợ thêm?

Nếu vẫn gặp vấn đề, cung cấp:
1. Screenshot màn hình khi search "lumentree" trong Add Integration
2. Logs từ Home Assistant (Settings → System → Logs)
3. Kết quả của script `check_and_restore.ps1`

