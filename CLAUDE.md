# lumentreeHA â€” Home Assistant Lumentree Solar Inverter Integration

HACS custom integration for Lumentree hybrid solar inverters. Real-time MQTT monitoring, energy statistics, battery management, PV power tracking. MIT licensed.

## Project Overview

Monitors Lumentree inverters via MQTT. Provides 100+ sensors per inverter: PV input (2 strings), battery (voltage/current/power/SOC/temperature), grid (import/export), load, daily/monthly/yearly/total energy, inverter status/temperature/faults.

### Stack
- **Language**: Python 3.11+
- **Framework**: Home Assistant integration (config_flow)
- **Protocol**: MQTT (paho-mqtt)
- **Build**: pyproject.toml (uv/pip)

## Architecture

```
â”œâ”€â”€ __init__.py          # Integration entry â€” async_setup_entry, MQTT subscribe
â”œâ”€â”€ const.py             # MQTT topics, device classes, units, defaults
â”œâ”€â”€ config_flow.py       # UI config flow â€” MQTT broker + inverter settings
â”œâ”€â”€ common.py            # Shared utilities, value parsing
â”œâ”€â”€ sensor.py            # LumentreeSensor (Entity)
â”œâ”€â”€ binary_sensor.py     # Status/fault binary sensors
â”œâ”€â”€ diagnostics.py       # HA diagnostics support
â”œâ”€â”€ core/                # MQTT client, data models
â”œâ”€â”€ coordinators/        # DataUpdateCoordinator per inverter
â”œâ”€â”€ entities/            # Entity definitions by sensor group
â”œâ”€â”€ services/            # HA service definitions
â”œâ”€â”€ models/              # Pydantic data models
â”œâ”€â”€ translations/        # i18n (strings.json)
â””â”€â”€ tests/               # pytest test suite
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

- **Pattern**: HA DataUpdateCoordinator pattern â€” coordinator polls data, entities read from coordinator
- **MQTT topics**: Subscribed in `__init__.py`, parsed in `common.py`, stored in coordinator
- **Entities**: One entity per sensor value, grouped by domain (sensor/binary_sensor)
- **Config flow**: UI-based setup, no manual YAML required. Validates MQTT connectivity.
- **Naming**: Follow HA conventions â€” snake_case files, PascalCase classes
- **Types**: All new code must have type hints. Pydantic models in `models/` for data structures.
- **Anti-patterns**: Avoid blocking calls in async context. Use `async_add_executor_job` for MQTT operations.
- **Translation**: All user-facing strings in `strings.json`, no hardcoded English in entities.

## MQTT Topic Structure

```
lumentree/{serial_number}/pv/input1/power
lumentree/{serial_number}/pv/input1/voltage
lumentree/{serial_number}/battery/power
lumentree/{serial_number}/battery/soc
lumentree/{serial_number}/grid/power
lumentree/{serial_number}/load/power
lumentree/{serial_number}/energy/total
...
```

## HACS

- `hacs.json` at root, `manifest.json` for HA metadata
- Version tracked via GitHub Releases (semantic versioning)
- HA >= 2024.3.0 required
