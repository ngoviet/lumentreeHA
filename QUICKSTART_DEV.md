# Quick Start Guide for Developers

Hướng dẫn nhanh để chạy tests, lints, và phát triển Lumentree integration.

## Prerequisites

- Python 3.12+
- Home Assistant Core 2025.x
- Git

## Setup Development Environment

### 1. Tạo Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/Mac
python -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
cd custom_components/lumentree
pip install -r requirements_dev.txt
```

## Running Tests

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_setup_teardown.py -v
pytest tests/test_mqtt_flow.py -v
pytest tests/test_stats_decode.py -v
pytest tests/test_config_flow.py -v
```

### Run with Coverage

```bash
pytest tests/ --cov=custom_components.lumentree --cov-report=html
```

## Linting

### Run Ruff

```bash
ruff check custom_components/lumentree
```

### Auto-fix with Ruff

```bash
ruff check custom_components/lumentree --fix
```

### Run MyPy

```bash
mypy custom_components/lumentree --ignore-missing-imports
```

## Hassfest

### Validate Integration

```bash
hassfest --integration custom_components/lumentree
```

## Debug Logging

Thêm vào `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.lumentree: debug
    custom_components.lumentree.core.mqtt_client: debug
    custom_components.lumentree.core.realtime_parser: debug
```

## Development Workflow

1. **Make Changes**: Edit code in `custom_components/lumentree/`
2. **Run Lints**: `ruff check . && mypy .`
3. **Run Tests**: `pytest tests/ -v`
4. **Test in HA**: Copy to HA `custom_components/` directory and restart
5. **Check Logs**: Monitor `home-assistant.log` for errors

## Common Issues

### Import Errors in Tests

Nếu gặp lỗi import, đảm bảo bạn đang chạy từ thư mục gốc của integration:

```bash
cd custom_components/lumentree
pytest tests/
```

### Type Checking Errors

Một số third-party libraries (paho-mqtt, crcmod) không có type stubs. Sử dụng `--ignore-missing-imports` với mypy.

### Test Failures

Kiểm tra:
- Python version (cần 3.12+)
- Dependencies đã được install đầy đủ
- Home Assistant test fixtures có sẵn

## CI/CD

Tests tự động chạy trên GitHub Actions khi:
- Push to main/master/develop branches
- Create pull request

Xem `.github/workflows/test.yml` để biết chi tiết.

