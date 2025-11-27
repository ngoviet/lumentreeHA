# Lumentree Integration Documentation

This directory contains documentation, guides, and example code for the Lumentree Home Assistant integration.

## 📁 Directory Structure

```
docs/
├── README.md                    # This file
├── api/                         # API documentation
│   ├── API_PROTOCOL.md         # API endpoints and authentication
│   ├── API_TEST_GUIDE.md       # API testing guide
│   ├── ERROR_HANDLING.md       # Error handling patterns
│   └── CACHE_AND_BACKFILL.md   # Cache management
├── dashboard/                   # Dashboard configuration examples
│   ├── DASHBOARD_README.md     # Dashboard usage guide
│   ├── TROUBLESHOOTING_GUIDE.md # Dashboard troubleshooting
│   ├── dashboard_pv_grid.yaml  # PV and Grid chart example
│   ├── dashboard_total_load.yaml # Total load chart example
│   ├── dashboard_battery_charge_discharge.yaml # Battery chart example
│   ├── dashboard_daily_stats.yaml # Daily statistics dashboard
│   ├── dashboard_monthly_stats.yaml # Monthly statistics dashboard
│   └── dashboard_yearly_stats.yaml # Yearly statistics dashboard
└── examples/                    # Code examples
    └── backfill_2024.yaml      # Example automation for backfilling historical data
```

## 📚 Documentation

### API Documentation
- **[API Protocol](api/API_PROTOCOL.md)**: Complete API reference including authentication, endpoints, and request/response formats
- **[API Testing Guide](api/API_TEST_GUIDE.md)**: Step-by-step guide for testing API endpoints
- **[Error Handling](api/ERROR_HANDLING.md)**: Error handling patterns and best practices
- **[Cache and Backfill](api/CACHE_AND_BACKFILL.md)**: Cache management strategies and backfill algorithms

### Dashboard Guides
- **[Dashboard README](dashboard/DASHBOARD_README.md)**: Overview and usage instructions for dashboards
- **[Troubleshooting Guide](dashboard/TROUBLESHOOTING_GUIDE.md)**: Common issues and solutions for dashboard configuration

### Example Dashboards
- **PV & Grid Chart**: Real-time power generation and grid import/export visualization
- **Total Load Chart**: Consumption monitoring with 5-minute interval data
- **Battery Charge/Discharge**: Battery energy flow visualization
- **Daily Statistics**: Comprehensive daily energy statistics dashboard
- **Monthly Statistics**: Monthly energy statistics with savings calculation
- **Yearly Statistics**: Yearly energy statistics with savings calculation

## 🔧 Usage

### Replacing Placeholders

All example files use placeholder values that need to be replaced with your actual device information:

- `YOUR_DEVICE_ID`: Replace with your actual device ID (e.g., `H123456789`)
- `sensor.device_YOUR_DEVICE_ID_*`: Replace with your actual sensor entity IDs

### Example

Before using a dashboard YAML file:

```yaml
# Original (example)
entity: sensor.device_YOUR_DEVICE_ID_pv_today

# Replace with your device ID
entity: sensor.device_YOUR_DEVICE_ID_pv_today
```

## 📝 Notes

- All example files have been sanitized to remove sensitive information
- Device IDs, tokens, and other sensitive data have been replaced with placeholders
- Make sure to replace all placeholders before using the examples in your Home Assistant setup

## 🤝 Contributing

When contributing examples or documentation:

1. Always use placeholders (`YOUR_DEVICE_ID`, etc.) instead of real device information
2. Test examples to ensure they work correctly
3. Update this README if adding new documentation or examples

## 📄 License

This documentation is part of the Lumentree Integration project and follows the same license as the main project.

