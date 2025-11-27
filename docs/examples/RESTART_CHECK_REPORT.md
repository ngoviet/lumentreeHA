# Báo cáo Kiểm tra và Restart Home Assistant

## ✅ Kết quả Kiểm tra

### 1. Cấu trúc Integration ✓
Đã kiểm tra và xác nhận:
- ✅ Tất cả file bắt buộc tồn tại (`__init__.py`, `manifest.json`, `config_flow.py`, `const.py`, `strings.json`)
- ✅ `manifest.json` hợp lệ với domain="lumentree", config_flow=true
- ✅ Domain name nhất quán trong tất cả files
- ✅ Không có syntax errors
- ✅ Cấu trúc thư mục đầy đủ (core/, entities/, coordinators/, services/, models/)

### 2. Restart Home Assistant
- ⚠️ Script restart bị chặn bởi PowerShell execution policy
- 💡 **Cần restart thủ công**: Settings → System → Restart

### 3. Kiểm tra Config Entries
Sau khi restart, cần kiểm tra:
- Số lượng entries lumentree
- Trạng thái của từng entry (loaded/not_loaded)
- Device ID và Device SN của entries

### 4. Kiểm tra Logs
Sau khi restart, cần kiểm tra logs để xem:
- Integration có được load không
- Có lỗi nào không
- MQTT connection status

## 📋 Hướng dẫn Thực hiện

### Bước 1: Restart Home Assistant
1. Mở Home Assistant UI
2. Vào **Settings** → **System**
3. Click **Restart**
4. Đợi HA khởi động lại hoàn toàn (khoảng 1-2 phút)

### Bước 2: Kiểm tra Config Entries
Chạy lệnh sau trong PowerShell:
```powershell
$json = Get-Content "\\192.168.10.15\config\.storage\core.config_entries" -Raw -Encoding UTF8 | ConvertFrom-Json
$lumentree = $json.data.entries | Where-Object { $_.domain -eq "lumentree" }
Write-Host "Found $($lumentree.Count) lumentree entries"
$lumentree | ForEach-Object { Write-Host "Entry: $($_.entry_id), State: $($_.state)" }
```

### Bước 3: Kiểm tra Logs
Chạy lệnh sau:
```powershell
Get-Content "\\192.168.10.15\config\home-assistant.log.1" -Tail 100 | Select-String "lumentree"
```

### Bước 4: Kiểm tra UI
1. Vào **Settings** → **Devices & Services**
2. Tìm **Lumentree Inverter** trong danh sách
3. Nếu không thấy:
   - Click **"+ ADD INTEGRATION"**
   - Tìm kiếm "lumentree"
   - Add integration với thông tin device

## 🎯 Kết luận

**Cấu trúc integration HOÀN TOÀN ĐÚNG!**

Vấn đề không phải do cấu trúc code. Có thể do:
1. Home Assistant cache chưa được clear
2. Integration chưa được scan sau khi restart
3. Cần add lại integration từ UI

## 🔧 Giải pháp

### Nếu không tìm thấy integration trong UI:
1. **Clear cache** (nếu cần):
   ```powershell
   # Backup trước
   Copy-Item "\\192.168.10.15\config\.storage\core.config_entries" "\\192.168.10.15\config\.storage\core.config_entries.backup"
   ```

2. **Restart Home Assistant** (Settings → System → Restart)

3. **Add integration từ UI**:
   - Settings → Devices & Services
   - Click "+ ADD INTEGRATION"
   - Tìm "lumentree" hoặc "Lumentree Inverter"
   - Điền thông tin:
     - Device ID (ví dụ: H240909079)
     - Device SN (ví dụ: 01K99JBTP1Q9ERQ1BESFXD700R)
     - HTTP Token (từ app Lumentree)

### Nếu có entry nhưng "Not loaded":
1. Kiểm tra logs để tìm lỗi
2. Thử reload integration
3. Nếu vẫn lỗi, xóa và add lại

## ✅ Checklist

- [x] Cấu trúc integration đúng
- [x] File bắt buộc đầy đủ
- [x] Domain name nhất quán
- [x] Syntax không lỗi
- [ ] HA đã restart
- [ ] Config entries đã kiểm tra
- [ ] Logs đã kiểm tra
- [ ] Integration hiển thị trong UI

## 📞 Cần hỗ trợ thêm?

Nếu vẫn gặp vấn đề sau khi restart và kiểm tra:
1. Cung cấp kết quả của lệnh kiểm tra config entries
2. Cung cấp logs liên quan đến lumentree
3. Screenshot màn hình khi search "lumentree" trong Add Integration

