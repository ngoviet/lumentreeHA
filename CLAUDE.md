# lumentreeHA — Home Assistant Lumentree Solar Inverter Integration

HACS custom integration for Lumentree hybrid solar inverters. Real-time MQTT monitoring, energy statistics, battery management, PV power tracking. MIT licensed.

## Project Overview

Monitors Lumentree inverters via MQTT. Provides 83 sensor entities per inverter (55 real-time + 28 statistics): PV input (2 strings), battery (voltage/current/power/SOC/temperature), grid (import/export), load, daily/monthly/yearly/total energy, inverter status/temperature.

### Stack
- **Language**: Python 3.11+
- **Framework**: Home Assistant integration (config_flow)
- **Protocol**: MQTT (paho-mqtt)
- **Build**: pyproject.toml (uv/pip)

## Architecture

```
├── __init__.py          # Integration entry — async_setup_entry, MQTT subscribe
├── const.py             # MQTT topics, device classes, units, defaults
├── config_flow.py       # UI config flow — MQTT broker + inverter settings
├── common.py            # build_device_info (DeviceInfo for sensor/binary_sensor)
├── sensor.py            # LumentreeSensor (Entity)
├── binary_sensor.py     # Status/fault binary sensors
├── diagnostics.py       # HA diagnostics support
├── core/                # HTTP API client, MQTT client, Modbus parser, exceptions
├── coordinators/        # DataUpdateCoordinator per inverter
├── entities/            # Entity definitions by sensor group
├── services/            # HA service definitions
├── translations/        # i18n (en.json; source strings in strings.json)
└── tests/               # pytest test suite
```

## Build/Test

```bash
# Install dev dependencies
uv pip install -r requirements_dev.txt

# Lint
ruff check .

# Type check
mypy .

# Run tests
pytest tests/ -v

# Validate HA manifest
python -m hassfest
```

## Code Conventions

- **Pattern**: HA DataUpdateCoordinator pattern — coordinator polls data, entities read from coordinator
- **MQTT topics**: Subscribed in `core/mqtt_client.py`, parsed in `core/realtime_parser.py`, stored in coordinator
- **Entities**: One entity per sensor value, grouped by domain (sensor/binary_sensor)
- **Config flow**: UI-based setup, no manual YAML required. Validates MQTT connectivity.
- **Naming**: Follow HA conventions — snake_case files, PascalCase classes
- **Types**: All new code must have type hints.
- **Anti-patterns**: Avoid blocking calls in async context. Use `async_add_executor_job` for any file or network I/O — coordinators, the API client and the MQTT client all do.
- **Anti-patterns**: Never call a vendor write endpoint (`bind device`, `register`, `upSnAddress`, `setRemarkName`, `delDevice`, `device/sendMsg`). `iot_class: cloud_polling` means read-only Tier 1 only.
- **Translation**: All user-facing strings in `strings.json`, no hardcoded English in entities.

## MQTT Topic Structure

Two topics per inverter, both built in `const.py` and formatted in `core/mqtt_client.py`:

```
reportApp/{device_sn}      # subscribe — the device publishes its Modbus-RTU frame here
listenApp/{device_sn}      # publish   — the integration sends read commands here
```

The payload is a hex-encoded Modbus-RTU frame, not JSON, and there is no per-metric topic tree.
See [docs/api/REGISTER_MAP.md](docs/api/REGISTER_MAP.md) for the register layout.

## HACS

- `hacs.json` at root, `manifest.json` for HA metadata
- Version tracked via GitHub Releases (semantic versioning)
- Effective HA floor is **2024.4**, not the `2023.1.0` declared in `hacs.json`: `config_flow.py` does a runtime `from homeassistant.config_entries import ConfigFlowResult`, and that symbol only exists from 2024.4. On 2023.1–2024.3 the integration installs and then fails at setup.
- Python 3.11+ (`asyncio.timeout` in the coordinators).
