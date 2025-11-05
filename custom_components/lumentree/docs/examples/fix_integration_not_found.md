# Khắc phục: Integration 'lumentree' not found

## Nguyên nhân

Lỗi `Integration 'lumentree' not found` thường xảy ra khi:
1. Home Assistant cache chưa được clear
2. Integration chưa được scan sau khi update code
3. Integration chưa được reload sau khi restart

## Giải pháp

### Bước 1: Clear Home Assistant Cache

**Cách 1: Từ UI (Nếu có quyền truy cập)**
1. Stop Home Assistant
2. Xóa thư mục `.homeassistant/cache` hoặc `.storage/core.config_entries`
3. Start lại Home Assistant

**Cách 2: Từ Terminal/SSH**
```bash
# Stop Home Assistant
# Xóa cache
rm -rf /config/.storage/core.config_entries
# Hoặc
rm -rf /config/.homeassistant/cache
# Start lại Home Assistant
```

### Bước 2: Force Reload Integration

1. Vào **Settings** → **Devices & Services**
2. Tìm **Lumentree Inverter**
3. Click **3 dots** (⋮) → **Delete** (cấu hình sẽ được giữ lại)
4. Click **Add Integration** → tìm **Lumentree Inverter**
5. Add lại integration với cùng thông tin

### Bước 3: Restart Home Assistant

1. Vào **Settings** → **System** → **Restart**
2. Đợi HA khởi động lại hoàn toàn
3. Kiểm tra logs xem integration có được load không

### Bước 4: Kiểm tra Logs

Vào **Settings** → **System** → **Logs** và tìm:
- `Setting up Lumentree: ...` - Xác nhận integration được load
- `Registering service lumentree.backfill_now` - Xác nhận services được đăng ký
- Lỗi nào liên quan đến `async_setup_entry` hoặc `manifest`

### Bước 5: Kiểm tra File Structure

Đảm bảo các file sau tồn tại:
- `__init__.py` ✓
- `manifest.json` ✓
- `strings.json` ✓
- `config_flow.py` ✓
- `const.py` ✓

### Bước 6: Kiểm tra Domain Name

Đảm bảo `domain` trong `manifest.json` khớp với `DOMAIN` trong `const.py`:
- `manifest.json`: `"domain": "lumentree"`
- `const.py`: `DOMAIN: Final = "lumentree"`

## Lưu ý

- Lỗi này thường không ảnh hưởng đến chức năng của integration
- Services vẫn hoạt động nếu được đăng ký trong `async_setup_entry`
- Chỉ là vấn đề với WebSocket API khi load manifest

## Nếu vẫn không được

1. **Check Python syntax:**
   ```bash
   python -m py_compile custom_components/lumentree/__init__.py
   ```

2. **Check manifest.json format:**
   ```bash
   python -m json.tool custom_components/lumentree/manifest.json
   ```

3. **Full restart:**
   - Stop Home Assistant hoàn toàn
   - Clear cache
   - Start lại

