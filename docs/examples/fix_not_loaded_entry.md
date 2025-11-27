# Khắc phục: Lumentree Integration "Not loaded"

## Nguyên nhân

Entry hiển thị "Not loaded" thường do:
1. **Entry duplicate**: Có 2 entries cho cùng một device, một entry cũ chưa được cleanup
2. **Entry bị lỗi trong quá trình setup**: `async_setup_entry` raise exception nhưng không được log rõ ràng
3. **Entry state không đúng**: Entry có state là "not_loaded" trong config

## Giải pháp

### Bước 1: Kiểm tra entries trong UI

1. Vào **Settings** → **Devices & Services** → **Lumentree**
2. Xác định entry nào đang "Not loaded"
3. Ghi lại **Entry ID** hoặc **Title** của entry đó

### Bước 2: Xóa entry duplicate/không hoạt động

**Cách 1: Từ UI (Khuyến nghị)**
1. Vào **Settings** → **Devices & Services** → **Lumentree**
2. Tìm entry có trạng thái "Not loaded"
3. Click **3 dots** (⋮) → **Delete**
4. Xác nhận xóa entry

**Cách 2: Từ Terminal (Nếu UI không cho phép)**

```powershell
# Backup config entries trước
Copy-Item "\\192.168.10.15\config\.storage\core.config_entries" "\\192.168.10.15\config\.storage\core.config_entries.backup"

# Đọc và sửa config entries
$json = Get-Content "\\192.168.10.15\config\.storage\core.config_entries" -Raw | ConvertFrom-Json
$lumentreeEntries = $json.data.entries | Where-Object { $_.domain -eq 'lumentree' }

# Tìm entry "not_loaded" hoặc duplicate
$notLoadedEntry = $lumentreeEntries | Where-Object { $_.state -eq 'not_loaded' -or $_.state -eq 'setup_error' }

if ($notLoadedEntry) {
    Write-Host "Found not_loaded entry: $($notLoadedEntry.entry_id)"
    # Xóa entry khỏi danh sách
    $json.data.entries = $json.data.entries | Where-Object { $_.entry_id -ne $notLoadedEntry.entry_id }
    # Lưu lại
    $json | ConvertTo-Json -Depth 10 | Set-Content "\\192.168.10.15\config\.storage\core.config_entries"
    Write-Host "Entry removed. Please restart Home Assistant."
} else {
    Write-Host "No not_loaded entry found."
}
```

### Bước 3: Restart Home Assistant

Sau khi xóa entry:
1. Vào **Settings** → **System** → **Restart**
2. Đợi HA khởi động lại hoàn toàn
3. Kiểm tra lại UI xem entry "Not loaded" đã biến mất chưa

### Bước 4: Kiểm tra logs

Sau khi restart, kiểm tra logs:
```powershell
Get-Content "\\192.168.10.15\config\home-assistant.log" -Tail 50 | Select-String -Pattern "lumentree|Setting up Lumentree"
```

Đảm bảo chỉ còn 1 entry được setup thành công.

## Phòng ngừa

Để tránh entry duplicate trong tương lai:

1. **Luôn xóa entry cũ trước khi add entry mới** nếu device_id/device_sn giống nhau
2. **Không add entry mới nếu entry cũ đang hoạt động** cho cùng một device
3. **Kiểm tra logs** sau mỗi lần add integration để đảm bảo không có lỗi

## Lưu ý

- Entry "Not loaded" không ảnh hưởng đến entry đang hoạt động
- Xóa entry "Not loaded" sẽ không mất dữ liệu của entry đang hoạt động
- Nếu cả 2 entries đều "Not loaded", cần kiểm tra logs để tìm nguyên nhân lỗi setup

