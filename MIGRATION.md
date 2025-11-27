# Migration Guide

Hướng dẫn migrate từ version cũ sang version mới của Lumentree integration.

## Version 4.0.4+ (Sau Audit)

### Breaking Changes

**Không có breaking changes** - Tất cả thay đổi đều backward compatible.

### New Features

1. **Thread-safety Improvements**
   - Sửa lỗi thread-unsafe trong MQTT client
   - Batch timer được schedule đúng cách từ event loop

2. **Better Cleanup**
   - MQTT client unsubscribe khi disconnect
   - Tất cả timers được cancel đúng cách
   - Coordinators được shutdown khi unload

3. **Diagnostics Support**
   - Thêm diagnostics endpoint để debug
   - Export config và status (không lộ secrets)

4. **Parser Refactoring**
   - Tách parser thành `realtime_parser.py` và `stats_parser.py`
   - Giữ backward compatibility với `modbus_parser.py`

### Migration Steps

1. **Update Code**
   ```bash
   # Backup current code
   cp -r custom_components/lumentree custom_components/lumentree.backup
   
   # Update code (git pull hoặc copy files mới)
   ```

2. **Restart Home Assistant**
   - Vào Settings → System → Restart
   - Hoặc reload integration: Settings → Devices & Services → Lumentree → Reload

3. **Verify**
   - Kiểm tra logs không có lỗi thread-safety
   - Kiểm tra sensors hoạt động bình thường
   - Kiểm tra MQTT connection ổn định

### Rollback Plan

Nếu gặp vấn đề, có thể rollback:

1. **Restore Backup**
   ```bash
   rm -rf custom_components/lumentree
   cp -r custom_components/lumentree.backup custom_components/lumentree
   ```

2. **Restart Home Assistant**

3. **Verify Rollback**
   - Kiểm tra integration hoạt động như trước

### Configuration Changes

**Không có thay đổi cấu hình** - Config entry format giữ nguyên.

### Entity Changes

**Không có thay đổi entities**:
- Unique_id giữ nguyên: `{device_sn}_{key}`
- Entity_id giữ nguyên
- Device_class, state_class, unit giữ nguyên

### API Changes

**Không có thay đổi API**:
- HTTP API endpoints giữ nguyên
- MQTT topics giữ nguyên
- Service calls giữ nguyên

## Troubleshooting

### Issue: Thread-safety Warnings

**Symptom**: Logs có cảnh báo về thread-unsafe operations

**Solution**: Đảm bảo đã update lên version mới nhất

### Issue: MQTT Not Disconnecting

**Symptom**: MQTT client không disconnect khi unload

**Solution**: Đảm bảo đã update lên version mới nhất với cleanup improvements

### Issue: Import Errors

**Symptom**: Lỗi import `modbus_parser`

**Solution**: `modbus_parser.py` vẫn hoạt động như cũ (re-export từ `realtime_parser.py`). Nếu vẫn lỗi, kiểm tra file structure.

## Support

Nếu gặp vấn đề khi migrate:
1. Kiểm tra logs: `home-assistant.log`
2. Bật debug logging (xem QUICKSTART_DEV.md)
3. Tạo issue trên GitHub với logs và error messages

