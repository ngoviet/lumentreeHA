# Khắc phục: Services không xuất hiện

## Nguyên nhân có thể

1. **Integration chưa được reload** sau khi update code
2. **Lỗi trong quá trình setup** khiến services không được đăng ký
3. **Code mới chưa được copy** vào HA deployment

## Cách khắc phục

### Bước 1: Kiểm tra code đã được copy chưa

Đảm bảo code đã được copy từ git repo sang HA deployment:
- Git repo: `\\192.168.10.33\ha\integration\lumentree\custom_components\lumentree`
- HA deployment: `\\192.168.10.15\config\custom_components\lumentree`

### Bước 2: Kiểm tra logs

Vào **Settings** → **System** → **Logs** và tìm:
- `Setting up Lumentree: ...` - Xác nhận integration được load
- `Registering service lumentree.backfill_now` - Xác nhận service được đăng ký
- Lỗi nào liên quan đến `async_register` hoặc `backfill`

### Bước 3: Restart Home Assistant

1. Vào **Settings** → **System** → **Restart**
2. Đợi HA khởi động lại hoàn toàn
3. Kiểm tra lại services

### Bước 4: Reload Integration

1. Vào **Settings** → **Devices & Services**
2. Tìm integration **Lumentree Inverter**
3. Click **3 dots** (⋮) → **Reload**
4. Kiểm tra lại services

### Bước 5: Kiểm tra services trong Developer Tools

1. Vào **Developer Tools** → **Services**
2. Tìm domain: `lumentree`
3. Xem danh sách services:
   - `lumentree.backfill_now`
   - `lumentree.backfill_all`
   - `lumentree.smart_backfill`
   - `lumentree.recompute_month_year`
   - Và các services khác

### Bước 6: Nếu vẫn không thấy

1. **Remove và re-add integration:**
   - Vào **Settings** → **Devices & Services**
   - Tìm **Lumentree Inverter**
   - Click **Delete** (cấu hình sẽ được giữ lại)
   - Add lại integration

2. **Clear Home Assistant cache:**
   - Stop Home Assistant
   - Xóa thư mục `.homeassistant/cache` (nếu có)
   - Start lại Home Assistant

## Lưu ý về lỗi translation

Lỗi `Failed to load integration for translation: Integration 'lumentree' not found` thường không ảnh hưởng đến services. Services được đăng ký trong code (`__init__.py`), không phải từ `services.yaml`.

`services.yaml` chỉ dùng cho UI translations (tên và mô tả hiển thị trong Developer Tools).

## Kiểm tra nhanh

Chạy script này trong **Developer Tools** → **Template**:

```yaml
{{ states('sensor.device_H240909079_pv_today') }}
```

Nếu sensor có giá trị → Integration đã được load. Nếu không → Integration chưa được setup.

