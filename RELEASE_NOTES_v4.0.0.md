# Release v4.0.0 - Major Statistics Enhancement

## 🚀 Major Statistics Enhancement

This is a major version release introducing comprehensive statistics tracking across multiple time periods.

### ✨ New Features

**Monthly Statistics Sensors:**
- `pv_month` - PV generation for current month (kWh)
- `grid_in_month` - Grid import for current month (kWh)
- `load_month` - Load consumption for current month (kWh)
- `essential_month` - Essential load for current month (kWh)
- `total_load_month` - Total load for current month (kWh)
- `charge_month` - Battery charge for current month (kWh)
- `discharge_month` - Battery discharge for current month (kWh)
- `saved_month` - Energy saved for current month (kWh)
- `savings_vnd_month` - Cost savings for current month (VND)

**Yearly Statistics Sensors:**
- `pv_year` - PV generation for current year (kWh)
- `grid_in_year` - Grid import for current year (kWh)
- `load_year` - Load consumption for current year (kWh)
- `essential_year` - Essential load for current year (kWh)
- `total_load_year` - Total load for current year (kWh)
- `charge_year` - Battery charge for current year (kWh)
- `discharge_year` - Battery discharge for current year (kWh)
- `saved_year` - Energy saved for current year (kWh)
- `savings_vnd_year` - Cost savings for current year (VND)

**Total/Lifetime Statistics Sensors:**
- `pv_total` - Lifetime PV generation (kWh)
- `grid_in_total` - Lifetime grid import (kWh)
- `load_total` - Lifetime load consumption (kWh)
- `essential_total` - Lifetime essential load (kWh)
- `total_load_total` - Lifetime total load (kWh)
- `charge_total` - Lifetime battery charge (kWh)
- `discharge_total` - Lifetime battery discharge (kWh)
- `saved_total` - Lifetime energy saved (kWh)
- `savings_vnd_total` - Lifetime cost savings (VND)

### 🔧 Technical Implementation

**New Coordinators:**
- `MonthlyStatsCoordinator` - Aggregates daily data into monthly statistics
- `YearlyStatsCoordinator` - Aggregates monthly data into yearly statistics with monthly arrays for charting
- `TotalStatsCoordinator` - Calculates lifetime totals from all cached historical data

**Data Aggregation:**
- Monthly statistics computed from daily cache data
- Yearly statistics include monthly breakdown arrays for visualization
- Total statistics calculated from all available historical data
- Automatic month/year finalization when periods change
- Cache-based aggregation for performance

**Historical Data Support:**
- Monthly arrays exposed in yearly coordinator for charting
- Support for viewing statistics across multiple years
- Automatic recalculation when new data becomes available

### 📊 Benefits

- **Comprehensive Tracking**: Monitor energy statistics across daily, monthly, yearly, and lifetime periods
- **Dashboard Ready**: Monthly arrays enable advanced charting and visualization
- **Performance Optimized**: Cache-based aggregation minimizes API calls
- **Automatic Updates**: Coordinators automatically update when periods change
- **Historical Analysis**: Track energy trends over months and years

### 🔄 Breaking Changes

- None - fully backward compatible with v3.1.0
- New sensors are automatically added when integration is updated
- Existing daily statistics sensors remain unchanged

### 📝 Migration Notes

- No migration required - automatic upgrade from v3.1.0
- All existing configurations remain valid
- New sensors will appear after Home Assistant restart
- Monthly/yearly/total data will populate automatically from cache

