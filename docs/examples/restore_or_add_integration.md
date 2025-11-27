# Khôi phục hoặc Add lại Lumentree Integration

## Tình huống: Đã xóa nhầm entry và không tìm thấy integration

### Bước 1: Kiểm tra xem còn entry nào không

Chạy lệnh này trong PowerShell:
```powershell
$json = Get-Content "\\192.168.10.15\config\.storage\core.config_entries" -Raw -Encoding UTF8 | ConvertFrom-Json
$lumentree = $json.data.entries | Where-Object { $_.domain -eq 'lumentree' }
Write-Host "Found $($lumentree.Count) lumentree entries"
```

### Bước 2: Nếu có backup, khôi phục

Nếu bạn đã chạy script `remove_duplicate_entry.ps1`, sẽ có backup file:
```powershell
# Liệt kê các backup
Get-ChildItem "\\192.168.10.15\config\.storage\core.config_entries.backup.*" | Sort-Object LastWriteTime -Descending

# Khôi phục từ backup mới nhất
$backup = Get-ChildItem "\\192.168.10.15\config\.storage\core.config_entries.backup.*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $backup.FullName "\\192.168.10.15\config\.storage\core.config_entries" -Force
```

Sau đó restart Home Assistant.

### Bước 3: Add lại Integration (Nếu không có backup)

Nếu không có backup hoặc muốn add lại từ đầu:

#### 3.1. Từ UI Home Assistant:

1. **Vào Settings** → **Devices & Services**
2. Click nút **"+ ADD INTEGRATION"** (góc dưới bên phải)
3. Tìm kiếm **"lumentree"** hoặc **"Lumentree Inverter"**
4. Click vào integration
5. Điền thông tin:
   - **Device ID**: Ví dụ: `H240909079`
   - **Device SN**: Ví dụ: `01K99JBTP1Q9ERQ1BESFXD700R`
   - **HTTP Token**: Token từ app Lumentree
   - **MQTT Broker**: Thông tin MQTT broker (nếu cần)
6. Click **Submit**

#### 3.2. Kiểm tra thông tin cấu hình cũ (nếu có)

Nếu bạn nhớ thông tin device, có thể tìm trong:
- File `configuration.yaml` (nếu có cấu hình YAML cũ)
- App Lumentree trên điện thoại
- Logs cũ của Home Assistant

### Bước 4: Kiểm tra sau khi add

Sau khi add lại integration:

1. **Kiểm tra logs**:
   ```powershell
   Get-Content "\\192.168.10.15\config\home-assistant.log.1" -Tail 100 | Select-String "lumentree"
   ```

2. **Kiểm tra UI**:
   - Vào **Settings** → **Devices & Services** → **Lumentree**
   - Đảm bảo entry hiển thị với trạng thái "loaded"
   - Kiểm tra số lượng entities (thường là 58 entities)

3. **Kiểm tra sensors**:
   - Vào **Developer Tools** → **States**
   - Tìm các sensor bắt đầu với `sensor.device_` hoặc `sensor.h240909079_`

### Bước 5: Nếu vẫn không tìm thấy integration trong danh sách

Có thể do:
1. **Integration chưa được scan**: Restart Home Assistant
2. **File integration bị thiếu**: Kiểm tra thư mục `custom_components/lumentree`
3. **Cache chưa được clear**: Xóa cache và restart

**Script clear cache và restart:**
```powershell
# Clear cache
Remove-Item "\\192.168.10.15\config\.storage\core.entity_registry" -ErrorAction SilentlyContinue
Remove-Item "\\192.168.10.15\config\.storage\core.device_registry" -ErrorAction SilentlyContinue

# Restart HA (nếu có script)
& "\\192.168.10.15\config\ha-restart-tools\restart_ha.ps1"
```

### Thông tin cần thiết để add lại

Để add lại integration, bạn cần:
1. **Device ID**: ID của inverter (ví dụ: `H240909079`)
2. **Device SN**: Serial number (ví dụ: `01K99JBTP1Q9ERQ1BESFXD700R`)
3. **HTTP Token**: Token từ app Lumentree để truy cập API
4. **MQTT Broker** (nếu dùng MQTT riêng): Host, port, username, password

### Lưu ý

- Nếu bạn có backup, nên restore từ backup thay vì add lại
- Sau khi add lại, tất cả entities sẽ được tạo lại với `unique_id` mới
- Các automation/script tham chiếu đến entities cũ có thể cần update `entity_id`

