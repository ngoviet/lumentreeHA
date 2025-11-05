# LumentreeHA

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![maintenance](https://img.shields.io/badge/maintainer-ngoviet-blue.svg)](https://github.com/ngoviet)
[![GitHub release](https://img.shields.io/github/release/ngoviet/lumentreeHA.svg)](https://github.com/ngoviet/lumentreeHA/releases)
[![GitHub stars](https://img.shields.io/github/stars/ngoviet/lumentreeHA.svg?style=social&label=Star)](https://github.com/ngoviet/lumentreeHA)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=lumentreeHA&category=integration)

Home Assistant integration for Lumentree Solar Inverters (SUNT series) with real-time monitoring via MQTT and HTTP API.

![Sensors and Diagnostic Overview](images/sensors_entity_overview.png)

![Energy Monitoring Dashboard - 24h Charts](images/dashboard_energy_charts_24h.png)

![Statistics Summary Dashboard](images/dashboard_statistics_summary.png)

## Features

- **Real-time monitoring** via MQTT connection (5-second updates)
- **HTTP API integration** for device information and historical statistics
- **Comprehensive real-time sensors** (MQTT):
  - **PV Power**: Total, PV1, PV2 (power, voltage)
  - **Battery**: Voltage, current, SOC, power (absolute), status, type, cell monitoring
  - **Grid**: Voltage, frequency, power (import/export), status
  - **AC Input/Output**: Voltage, frequency, power, apparent power (VA)
  - **Load**: Power consumption, total load power (calculated)
  - **Device**: Temperature, master/slave status, device SN
- **Statistics sensors** (HTTP API with local cache):
  - **Daily**: PV generation, battery charge/discharge, grid input, load consumption (5 sensors)
  - **Monthly**: Totals plus daily arrays for charting (6 sensors: PV, Charge, Discharge, Grid, Load, Essential)
  - **Yearly**: Aggregated monthly totals (6 sensors)
  - **Lifetime/Total**: Cumulative statistics from device installation (6 sensors)
- **Binary sensors**: Online status, UPS mode detection
- **Cache management services**:
  - Automatic backfill on first setup and nightly updates
  - Manual services: backfill_now, backfill_all, backfill_gaps, recompute_month_year, purge_cache
  - Gap detection and filling for missing historical data
- **Performance optimizations**:
  - Parallel API calls (3x faster data fetching)
  - Batch cache I/O operations (30-50% faster backfill)
  - Adaptive exponential backoff for rate limiting
- **Robust error handling** with automatic MQTT reconnection

## Supported Devices

- **SUNT-4.0KW-H** (Primary support)
- **Other SUNT series inverters** (Compatible)

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=lumentreeHA&category=integration)

1. Open **HACS** in your Home Assistant instance
2. Go to **Integrations**
3. Click the **three dots** (⋮) in the top right corner
4. Select **Custom repositories**
5. Add this repository:
   - **Repository**: `https://github.com/ngoviet/lumentreeHA`
   - **Category**: `Integration`
6. Click **Add**
7. Search for **"LumentreeHA"** and install it
8. Restart Home Assistant
9. Add the integration via **Configuration** → **Integrations**

### Manual Installation

1. Download the latest release from [GitHub](https://github.com/ngoviet/lumentreeHA/releases)
2. Copy the `custom_components/lumentree` folder to your Home Assistant `custom_components/` directory
3. Restart Home Assistant
4. Add the integration via **Configuration** → **Integrations**

## Configuration

### Adding the Integration

1. Go to **Configuration** → **Integrations**
2. Click **Add Integration**
3. Search for **"Lumentree Inverter"**
4. Enter your device information:
   - **Device SN**: Serial number of your inverter (e.g., `H240909099`)
   - **Device ID**: Device ID (usually same as SN)
   - **Device Name**: Friendly name for your device
   - **HTTP Token**: Authentication token from Lumentree app
5. Click **Submit**


## Requirements

- **Home Assistant**: 2022.7.0 or later
- **Python packages**:
  - `aiohttp>=3.8.0`
  - `paho-mqtt>=1.6.0`
  - `crcmod>=1.7`

## Sensors

### Real-time Sensors (MQTT)
- **PV Power**: Total solar generation power
- **PV1/PV2 Power**: Individual PV string power
- **Battery**: Voltage, current, SOC, power, status
- **Grid**: Voltage, frequency, power (import/export)
- **Load**: Power consumption
- **AC Output**: Voltage, frequency, power, VA
- **Device**: Temperature, UPS mode, master/slave status

### Statistics Sensors (HTTP API)
#### Daily Statistics
- **PV Generation**: Daily solar energy production
- **Battery Charge/Discharge**: Daily battery energy flow
- **Grid Import**: Daily grid energy import
- **Load Consumption**: Daily load energy usage
- **Essential Load**: Daily essential load consumption

#### Monthly Statistics
- **Monthly totals** for all categories (PV, Grid, Load, Essential, Charge, Discharge)
- **Daily arrays** for charting monthly trends

#### Yearly Statistics
- **Yearly totals** aggregated from monthly data

#### Lifetime Statistics
- **Total (lifetime) statistics** from device installation to now

### Binary Sensors
- **Online Status**: Device connectivity status
- **UPS Mode**: Whether device is in UPS mode

## Services

The integration provides several services for managing statistics cache and data backfill:

### `lumentree.backfill_now`
Backfill daily statistics for the last N days.

**Parameters:**
- `days` (optional): Number of past days to backfill (default: 365, max: 3650)

**Example:**
```yaml
service: lumentree.backfill_now
data:
  days: 30
```

### `lumentree.backfill_all`
Backfill all historical data (stops when encountering consecutive empty days or max years reached).

**Parameters:**
- `max_years` (optional): Maximum years to scan (default: 10)
- `empty_streak` (optional): Consecutive empty days threshold to stop (default: 14)

**Example:**
```yaml
service: lumentree.backfill_all
data:
  max_years: 5
  empty_streak: 14
```

### `lumentree.backfill_gaps`
Fill missing days in cache gradually (limited per run).

**Parameters:**
- `max_years` (optional): Recent years to check (default: 3)
- `max_days_per_run` (optional): Maximum days to fetch per run (default: 30)

**Example:**
```yaml
service: lumentree.backfill_gaps
data:
  max_years: 2
  max_days_per_run: 50
```

### `lumentree.recompute_month_year`
Recalculate monthly arrays and yearly totals from cached daily data for the current year.

**Example:**
```yaml
service: lumentree.recompute_month_year
```

### `lumentree.purge_cache`
Delete cached statistics for a specific year.

**Parameters:**
- `year` (optional): Year to purge (defaults to current year)

**Example:**
```yaml
service: lumentree.purge_cache
data:
  year: 2024
```

### `lumentree.mark_empty_dates`
Mark specific dates as empty in cache to skip them permanently.

**Parameters:**
- `year` (required): Year of dates to mark
- `dates` (required): List of dates in YYYY-MM-DD format

**Example:**
```yaml
service: lumentree.mark_empty_dates
data:
  year: 2025
  dates:
    - "2025-01-01"
    - "2025-12-31"
```

### `lumentree.mark_coverage_range`
Set the coverage range (earliest/latest dates) for a year.

**Parameters:**
- `year` (required): Year to set coverage range
- `earliest` (optional): Earliest date with complete data (YYYY-MM-DD)
- `latest` (optional): Latest date with complete data (YYYY-MM-DD)

**Example:**
```yaml
service: lumentree.mark_coverage_range
data:
  year: 2025
  earliest: "2025-01-15"
  latest: "2025-11-02"
```

## Cache Management

Statistics data is cached locally to reduce API calls and improve performance:

- **Cache Location**: `.storage/lumentree_stats/{device_id}/{year}.json`
- **Auto Backfill**: 
  - Full history backfill runs automatically on first setup (background)
  - Nightly incremental updates fill gaps for the previous day
- **Cache Structure**: Daily data, monthly arrays, yearly totals, and metadata
- **Manual Management**: Use services above to manage cache manually

## Troubleshooting

### Common Issues

**"Unrec len" errors in logs:**
- ✅ **Fixed in v2.0**: Parser now handles 202-byte data packets correctly
- Make sure you're using the latest version

**No data from sensors:**
- Verify your **HTTP token** is correct
- Check device is **online** in Lumentree app
- Review MQTT connection status in logs
- Ensure device SN and ID are correct

**Integration won't load:**
- Verify all **requirements** are installed
- Check Home Assistant **logs** for errors
- Ensure device SN and ID match exactly
- Try removing and re-adding the integration

**MQTT connection issues:**
- Check internet connectivity
- Verify MQTT broker is accessible
- Review firewall settings

**Statistics sensors not updating:**
- Statistics update on first setup (auto backfill in background)
- Daily statistics update via HTTP API (not real-time)
- Check cache location: `.storage/lumentree_stats/{device_id}/`
- Use `lumentree.backfill_now` service to fetch missing data
- Verify HTTP token is valid and device is online

**Monthly/Yearly sensors showing zeros:**
- Run `lumentree.recompute_month_year` service to recalculate aggregates
- Ensure daily data exists in cache for the period
- Check logs for cache loading errors

### Debug Logging

Enable detailed logging to troubleshoot issues:

```yaml
logger:
  default: info
  logs:
    custom_components.lumentree: debug
    homeassistant.components.mqtt: debug
```

## Contributing

We welcome contributions! Here's how you can help:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Development Setup

1. Clone the repository
2. Install development dependencies
3. Make your changes
4. Test with your Lumentree device
5. Submit a pull request

## Support

- 📧 **GitHub Issues**: [Report bugs or request features](https://github.com/ngoviet/lumentreeHA/issues)
- 💬 **Home Assistant Community**: [Join the discussion](https://community.home-assistant.io/)
- 📖 **Documentation**: Check this README and code comments

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **Lumentree** for providing the API and MQTT protocol
- **Home Assistant Community** for support and feedback
- **HACS** for making installation easy
- **Contributors** who help improve this integration

## Donate

If you find this integration useful, consider supporting the development:

[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-%23FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/ngoviet)

---

**Made with ❤️ for the Home Assistant community**