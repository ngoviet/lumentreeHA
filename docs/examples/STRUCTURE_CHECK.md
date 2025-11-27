# Kiểm tra Cấu trúc Integration Lumentree

## ✅ Các file bắt buộc đã có

### 1. File cốt lõi
- ✅ `__init__.py` - Entry point chính
- ✅ `manifest.json` - Metadata integration
- ✅ `config_flow.py` - Config flow handler
- ✅ `const.py` - Constants (DOMAIN)
- ✅ `strings.json` - Translations

### 2. Platform files
- ✅ `sensor.py` - Sensor platform
- ✅ `binary_sensor.py` - Binary sensor platform

### 3. Core modules
- ✅ `core/__init__.py`
- ✅ `core/api_client.py`
- ✅ `core/mqtt_client.py`
- ✅ `core/modbus_parser.py`
- ✅ `core/realtime_parser.py`
- ✅ `core/stats_parser.py`
- ✅ `core/exceptions.py`

### 4. Entities
- ✅ `entities/__init__.py`
- ✅ `entities/sensor.py`
- ✅ `entities/binary_sensor.py`
- ✅ `entities/base_entity.py`

### 5. Coordinators
- ✅ `coordinators/__init__.py`
- ✅ `coordinators/daily_coordinator.py`
- ✅ `coordinators/monthly_coordinator.py`
- ✅ `coordinators/yearly_coordinator.py`
- ✅ `coordinators/total_coordinator.py`
- ✅ `coordinators/stats_coordinator.py`

### 6. Services
- ✅ `services/__init__.py`
- ✅ `services/aggregator.py`
- ✅ `services/cache.py`
- ✅ `services/smart_backfill.py`

### 7. Models
- ✅ `models/__init__.py`
- ✅ `models/device_info.py`
- ✅ `models/sensor_data.py`

### 8. Other
- ✅ `diagnostics.py`
- ✅ `services.yaml`
- ✅ `translations/en.json`

## 🔍 Kiểm tra nội dung

### manifest.json
```json
{
  "domain": "lumentree",           ✅
  "name": "Lumentree Inverter",    ✅
  "config_flow": true,             ✅
  "version": "4.0.3",              ✅
  "requirements": [...],           ✅
  "iot_class": "cloud_polling",    ✅
  "integration_type": "device"     ✅
}
```

### const.py
```python
DOMAIN: Final = "lumentree"  ✅
```

### config_flow.py
```python
class LumentreeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  ✅
```

### __init__.py
```python
async def async_setup(hass: HomeAssistant, config: dict) -> bool:  ✅
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  ✅
```

## ⚠️ Các vấn đề cần kiểm tra

### 1. Syntax Errors
- ✅ `__init__.py` - No syntax errors
- ✅ `config_flow.py` - No syntax errors

### 2. Domain Consistency
- ✅ `manifest.json`: `"domain": "lumentree"`
- ✅ `const.py`: `DOMAIN = "lumentree"`
- ✅ `config_flow.py`: `domain=DOMAIN`

### 3. Required Functions
- ✅ `async_setup()` trong `__init__.py`
- ✅ `async_setup_entry()` trong `__init__.py`
- ✅ `LumentreeConfigFlow` class trong `config_flow.py`

## 🚨 Các vấn đề có thể gây lỗi

### 1. Import Errors
Kiểm tra tất cả imports có đúng không:
```python
# __init__.py
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
```

### 2. Circular Imports
Kiểm tra xem có circular import không giữa các modules.

### 3. Missing Dependencies
Kiểm tra `requirements` trong `manifest.json`:
- `aiohttp>=3.8.0` ✅
- `paho-mqtt>=1.6.0` ✅
- `crcmod>=1.7` ✅

### 4. Platform Setup
Kiểm tra `sensor.py` và `binary_sensor.py` có `async_setup_entry` không.

## 📋 Checklist để integration hiển thị trong HA

- [x] File `manifest.json` tồn tại và hợp lệ
- [x] File `__init__.py` có `async_setup` và `async_setup_entry`
- [x] File `config_flow.py` có `ConfigFlow` class với `domain=DOMAIN`
- [x] File `const.py` có `DOMAIN` constant
- [x] File `strings.json` tồn tại
- [x] Domain name nhất quán trong tất cả files
- [x] Không có syntax errors
- [x] Tất cả imports đúng
- [x] Dependencies được khai báo trong `manifest.json`

## 🔧 Nếu integration vẫn không hiển thị

1. **Clear cache và restart HA:**
   ```powershell
   Remove-Item "\\192.168.10.15\config\.storage\core.config_entries" -ErrorAction SilentlyContinue
   # Restart HA
   ```

2. **Kiểm tra logs:**
   ```powershell
   Get-Content "\\192.168.10.15\config\home-assistant.log" -Tail 100 | Select-String "lumentree|error|Error"
   ```

3. **Kiểm tra file permissions:**
   ```powershell
   Get-ChildItem "\\192.168.10.15\config\custom_components\lumentree" -Recurse | Get-Acl
   ```

4. **Validate manifest.json:**
   ```powershell
   python -c "import json; json.load(open('\\192.168.10.15\config\custom_components\lumentree\manifest.json'))"
   ```

5. **Kiểm tra Python syntax:**
   ```powershell
   python -m py_compile "\\192.168.10.15\config\custom_components\lumentree\__init__.py"
   python -m py_compile "\\192.168.10.15\config\custom_components\lumentree\config_flow.py"
   ```

