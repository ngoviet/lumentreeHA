# ApexCharts-Card Troubleshooting Guide for AI

## Overview
This document records common errors and solutions when working with `apexcharts-card` version 2.2.3 in Home Assistant dashboards. The solutions are documented primarily for AI assistants to understand and apply similar fixes in the future.

## Data Format and Input Structure

### Entity Attributes: series_5min_w

**Data Source:**
- **Entity Pattern**: `sensor.device_{device_sn}_{metric}_today`
  - Example: `sensor.device_YOUR_DEVICE_ID_charge_today`
  - Example: `sensor.device_YOUR_DEVICE_ID_discharge_today`
  - Example: `sensor.device_YOUR_DEVICE_ID_pv_today`
  - Example: `sensor.device_YOUR_DEVICE_ID_total_load_today`

**Attribute Format:**
- **Attribute Name**: `series_5min_w`
- **Data Type**: Can be either:
  - **String**: Comma-separated values like `"850, 850, 850, 0, 10, 10, 3, 3, ..."`
  - **Array**: Array of numbers `[850, 850, 850, 0, 10, 10, 3, 3, ...]`
- **Data Points**: 288 values (24 hours × 12 points per hour)
- **Time Interval**: 5 minutes per data point
- **Time Range**: 00:00:00 to 23:55:00 (full day)
- **Unit**: Watt (W)

**Data Structure Details:**
```javascript
// Example raw data
entity.attributes.series_5min_w = "850, 850, 850, 0, 10, 10, 3, 3, 3, 0, ..."
// or
entity.attributes.series_5min_w = [850, 850, 850, 0, 10, 10, 3, 3, 3, 0, ...]

// Index mapping to time:
// index 0   → 00:00 (hour 0, minute 0)
// index 1   → 00:05 (hour 0, minute 5)
// index 12  → 01:00 (hour 1, minute 0)
// index 143 → 11:55 (hour 11, minute 55)
// index 287 → 23:55 (hour 23, minute 55)
```

**Timestamp Calculation:**
```javascript
// Formula: hours = Math.floor(index / 12), minutes = (index % 12) * 5
const hours = Math.floor(index / 12);      // 0-23
const minutes = (index % 12) * 5;            // 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55
const timestamp = new Date(startOfDay);
timestamp.setHours(hours, minutes, 0, 0);
```

**Value Processing:**
- **Battery Charge**: Only positive values, clamped to 0-4000W
  ```javascript
  const val = parseFloat(value) || 0;
  return [timestamp.getTime(), Math.min(Math.max(val, 0), 4000)];
  ```

- **Battery Discharge**: Only positive values from source, then inverted to negative, clamped to 0-3000W (displayed as -3000W to 0W)
  ```javascript
  const val = parseFloat(value) || 0;
  return [timestamp.getTime(), -Math.min(Math.max(val, 0), 3000)];
  ```

- **Other Metrics (PV, Load, Grid)**: Direct values, clamped to 0 or min:0
  ```javascript
  const val = parseFloat(value) || 0;
  return [timestamp.getTime(), val];
  ```

### Expected Output Format

**data_generator must return:**
```javascript
// Array of [timestamp_ms, value] pairs
[
  [1728086400000, 850],  // 2024-10-05 00:00:00, 850W
  [1728086700000, 850],  // 2024-10-05 00:05:00, 850W
  [1728087000000, 850],  // 2024-10-05 00:10:00, 850W
  // ... 288 total points
]
```

**Timestamp Format:**
- **Type**: Unix timestamp in milliseconds (JavaScript `Date.getTime()`)
- **Example**: `1728086400000` = `2024-10-05 00:00:00 UTC`

**Value Format:**
- **Type**: Number (float or integer)
- **Unit**: Watt (W)
- **Range**: 
  - Charge: 0 to 4000W (positive)
  - Discharge: -3000W to 0W (negative)
  - Other: 0 to max (positive)

### Complete Data Generator Template

```javascript
data_generator: |
  return (function() {
    // 1. Get attribute with fallback
    const attr = entity.attributes.series_5min_w || [];
    
    // 2. Handle both string and array formats
    const arr = typeof attr === 'string' 
      ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) 
      : attr;
    
    // 3. Calculate start of day
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    
    // 4. Map to [timestamp, value] pairs
    return arr.map(function(value, index) {
      const hours = Math.floor(index / 12);      // 0-23
      const minutes = (index % 12) * 5;          // 0, 5, 10, ..., 55
      const timestamp = new Date(startOfDay);
      timestamp.setHours(hours, minutes, 0, 0);
      
      const val = parseFloat(value) || 0;
      
      // 5. Apply value processing (clamp, invert, etc.)
      // For charge: Math.min(Math.max(val, 0), 4000)
      // For discharge: -Math.min(Math.max(val, 0), 3000)
      // For others: val
      
      return [timestamp.getTime(), processedValue];
    });
  })();
```

## Critical Errors and Solutions

### 1. TypeError: Cannot read properties of null (reading 'yRatio')

**Error Description:**
```
Uncaught (in promise) TypeError: Cannot read properties of null (reading 'yRatio')
```

**Root Causes:**
- `data_generator` returns empty array `[]` or `null`
- `data_generator` returns invalid data format
- Entity attributes are missing or undefined
- Y-axis configuration conflicts with empty data

**Solutions:**

#### Solution 1: Ensure data_generator always returns valid data
```yaml
data_generator: |
  return (function() {
    const attr = entity.attributes.series_5min_w || [];
    const arr = typeof attr === 'string' ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) : attr;
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);

    return arr.map(function(value, index) {
      const hours = Math.floor(index / 12);
      const minutes = (index % 12) * 5;
      const timestamp = new Date(startOfDay);
      timestamp.setHours(hours, minutes, 0, 0);
      const val = parseFloat(value) || 0;
      return [timestamp.getTime(), val];
    });
  })();
```

**Key Points:**
- Use `|| []` fallback for missing attributes
- Handle both string (comma-separated) and array formats
- Always return array of `[timestamp, value]` pairs
- Never return empty array `[]` - at minimum return array with zero values

#### Solution 2: Remove fixed min/max from yaxis when data might be empty
```yaml
# ❌ BAD - Can cause yRatio error if data is empty
yaxis:
  - min: 0
    max: 4000

# ✅ GOOD - Let ApexCharts auto-scale
yaxis:
  - title:
      text: Power (W)
      style:
        fontSize: '12px'
```

#### Solution 3: Simplify data_generator - remove excessive error checking
```yaml
# ❌ BAD - Too many checks can cause issues
data_generator: |
  return (function() {
    if (!entity) return [];
    if (!entity.attributes) return [];
    if (!entity.attributes.series_5min_w) return [];
    // ... many more checks
  })();

# ✅ GOOD - Simple with fallback
data_generator: |
  return (function() {
    const attr = entity.attributes.series_5min_w || [];
    const arr = typeof attr === 'string' ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) : attr;
    // ... process data
  })();
```

---

### 2. Configuration Error: fill_opacity is extraneous

**Error Description:**
```
value.series[0].fill_opacity is extraneous
```

**Root Cause:**
- `apexcharts-card` version 2.2.3 does not support `fill_opacity` property in individual series configuration
- This property was removed or changed in this version

**Solution:**
```yaml
# ❌ BAD - fill_opacity in series config
series:
  - entity: sensor.example
    name: Example
    type: area
    fill_opacity: 0.3  # ❌ Not supported

# ✅ GOOD - Use fill.opacity in apex_config
apex_config:
  fill:
    opacity: 0.3  # ✅ Correct location
series:
  - entity: sensor.example
    name: Example
    type: area
    # fill_opacity removed
```

**Key Points:**
- `fill_opacity` is NOT supported in series-level config for apexcharts-card 2.2.3
- Use `apex_config.fill.opacity` instead
- Applies to all series in the chart

---

### 3. Configuration Error: yaxis[0].title is extraneous

**Error Description:**
```
value.yaxis[0].title is extraneous
```

**Root Cause:**
- `title` property placed at top-level `yaxis` instead of inside `apex_config.yaxis`

**Solution:**
```yaml
# ❌ BAD - title at top-level yaxis
yaxis:
  - min: 0
    title:
      text: Power (W)

# ✅ GOOD - title inside apex_config.yaxis
apex_config:
  yaxis:
    - title:
        text: Power (W)
        style:
          fontSize: '12px'
```

**Key Points:**
- All chart configuration must be inside `apex_config`
- Top-level `yaxis` is for apexcharts-card specific config (like `min`)
- `title` belongs in `apex_config.yaxis`

---

### 4. Legend Formatter Not Working / Chart Not Rendering

**Error Description:**
- Legend shows values like "0 kWh" instead of just series name
- Chart fails to render after adding formatter

**Root Cause:**
- Incorrect formatter syntax for apexcharts-card
- Missing `EVAL:` prefix required by apexcharts-card

**Solution:**
```yaml
# ❌ BAD - Direct function syntax
legend:
  formatter: function(seriesName) { return seriesName; }

# ✅ GOOD - Use EVAL: prefix with multi-line
legend:
  formatter: |
    EVAL:function(seriesName, opts) {
      return seriesName;
    }
```

**Key Points:**
- `EVAL:` prefix is REQUIRED for JavaScript functions in apexcharts-card
- Use multi-line YAML syntax with `|` for functions
- Same pattern applies to `tooltip.y.formatter`

**Example for Tooltip:**
```yaml
tooltip:
  y:
    formatter: |
      EVAL:function(val) {
        return Math.abs(val) + ' W';
      }
```

---

### 5. Data Format Mismatch: String vs Array

**Error Description:**
- `data_generator` fails because `series_5min_w` is sometimes a string, sometimes an array
- Entity provides comma-separated string: `"850, 850, 850, 0, 10, ..."`
- But code expects array format

**Solution:**
```yaml
data_generator: |
  return (function() {
    const attr = entity.attributes.series_5min_w || [];
    // Handle both string and array formats
    const arr = typeof attr === 'string' 
      ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) 
      : attr;
    
    // Process array...
    return arr.map(function(value, index) {
      // ...
    });
  })();
```

**Key Points:**
- Always check `typeof attr === 'string'` before processing
- Use `split(',')` and `map(parseFloat)` for string format
- Provide fallback `|| []` for missing data

---

### 6. Chart Type Compatibility Issues

**Error Description:**
- Column charts with negative values cause `yRatio` errors
- Chart shows "Loading..." indefinitely

**Solution:**
```yaml
# ❌ BAD - Column chart with negative values
chart:
  type: column
series:
  - name: Discharge
    type: column
    # Negative values cause issues

# ✅ GOOD - Use area chart for negative values
chart:
  type: area
series:
  - name: Discharge
    type: area
    # Negative values work fine
```

**Key Points:**
- Column charts may have issues with negative values in apexcharts-card 2.2.3
- Area charts handle negative values better
- For battery discharge (negative values), prefer area charts

---

### 7. Over-Complicated Configuration

**Error Description:**
- Chart works in simple test files but fails in complex configuration
- Too many nested properties cause parsing errors

**Solution:**
- Simplify configuration to match working examples
- Remove unnecessary properties
- Follow the pattern of `dashboard_total_load.yaml` or `dashboard_pv_grid.yaml`

**Working Pattern:**
```yaml
type: custom:apexcharts-card
header:
  title: Chart Title
  show: true
graph_span: 24h
span:
  start: day
now:
  show: false
apex_config:
  chart:
    type: area
    height: 300
  xaxis:
    type: datetime
    labels:
      format: HH:mm
      rotate: -45
  yaxis:
    - title:
        text: Power (W)
        style:
          fontSize: '12px'
  legend:
    position: top
    horizontalAlign: right
    fontSize: '12px'
  tooltip:
    shared: true
    intersect: false
  fill:
    opacity: 0.3
series:
  - entity: sensor.example
    name: Example
    type: area
    color: "#4169E1"
    stroke_width: 2
    data_generator: |
      return (function() {
        const attr = entity.attributes.series_5min_w || [];
        const arr = typeof attr === 'string' ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) : attr;
        const now = new Date();
        const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        return arr.map(function(value, index) {
          const hours = Math.floor(index / 12);
          const minutes = (index % 12) * 5;
          const timestamp = new Date(startOfDay);
          timestamp.setHours(hours, minutes, 0, 0);
          return [timestamp.getTime(), parseFloat(value) || 0];
        });
      })();
```

---

## Best Practices Summary

1. **Always provide fallbacks**: Use `|| []` for missing attributes
2. **Handle multiple data formats**: Support both string and array formats
3. **Simplify data_generator**: Avoid excessive error checking
4. **Use correct property locations**: `fill.opacity` in `apex_config`, not in series
5. **Use EVAL: prefix**: Required for JavaScript functions in apexcharts-card
6. **Prefer area charts**: Better compatibility with negative values
7. **Follow working examples**: Use `dashboard_total_load.yaml` as reference
8. **Avoid fixed min/max**: Let ApexCharts auto-scale when data might be empty
9. **Test incrementally**: Start simple, add complexity gradually
10. **Check version compatibility**: Solutions are for apexcharts-card 2.2.3

---

## Reference Files

- `dashboard_total_load.yaml` - Simple working example
- `dashboard_pv_grid.yaml` - Multi-series example
- `dashboard_battery_charge_discharge.yaml` - Final working version with negative values

---

## Debugging Checklist

When a chart fails to render:

1. ✅ Check browser console for JavaScript errors
2. ✅ Verify entity exists and has `series_5min_w` attribute
3. ✅ Ensure `data_generator` returns array of `[timestamp, value]` pairs
4. ✅ Check `fill_opacity` is not in series config (use `apex_config.fill.opacity`)
5. ✅ Verify `title` is in `apex_config.yaxis`, not top-level
6. ✅ Check formatter uses `EVAL:` prefix with multi-line syntax
7. ✅ Simplify configuration to match working examples
8. ✅ Try area chart instead of column if using negative values
9. ✅ Remove fixed `min/max` from yaxis if data might be empty
10. ✅ Verify YAML syntax is correct (no indentation errors)

---

## Correct Display Configuration

### Chart Display Requirements

**For Battery Charge & Discharge Chart:**

1. **Chart Type**: Use `area` chart (not `column`) for better negative value support
   ```yaml
   apex_config:
     chart:
       type: area
       height: 300
   ```

2. **Y-Axis Range**:
   - **Charge**: Display positive values from 0 to 4000W
   - **Discharge**: Display negative values from -3000W to 0W
   - **Auto-scaling**: Let ApexCharts auto-scale (don't set fixed min/max if data might be empty)
   ```yaml
   yaxis:
     - title:
         text: Power (W)
         style:
           fontSize: '12px'
     # No min/max - let it auto-scale
   ```

3. **Value Clamping**:
   - Charge values must be clamped: `Math.min(Math.max(val, 0), 4000)`
   - Discharge values must be clamped and inverted: `-Math.min(Math.max(val, 0), 3000)`

4. **Legend Configuration**:
   - Show only series name (no values)
   - Use `EVAL:` prefix for formatter
   ```yaml
   legend:
     position: top
     horizontalAlign: right
     fontSize: '12px'
     formatter: |
       EVAL:function(seriesName, opts) {
         return seriesName;
       }
   ```

5. **Tooltip Configuration**:
   - Display absolute values for both charge and discharge
   - Unit must be "W" (not "kWh")
   ```yaml
   tooltip:
     shared: true
     intersect: false
     y:
       formatter: |
         EVAL:function(val) {
           return Math.abs(val) + ' W';
         }
   ```

6. **Fill Opacity**:
   - Set in `apex_config.fill.opacity`, not in series config
   ```yaml
   apex_config:
     fill:
       opacity: 0.3
   ```

### Complete Working Example: Battery Charge & Discharge

```yaml
type: custom:apexcharts-card
header:
  title: Battery Charge & Discharge
  show: true
graph_span: 24h
span:
  start: day
now:
  show: false
apex_config:
  chart:
    type: area
    height: 300
  xaxis:
    type: datetime
    labels:
      format: HH:mm
      rotate: -45
  yaxis:
    - title:
        text: Power (W)
        style:
          fontSize: '12px'
  legend:
    position: top
    horizontalAlign: right
    fontSize: '12px'
    formatter: |
      EVAL:function(seriesName, opts) {
        return seriesName;
      }
  tooltip:
    shared: true
    intersect: false
    y:
      formatter: |
        EVAL:function(val) {
          return Math.abs(val) + ' W';
        }
  fill:
    opacity: 0.3
series:
      - entity: sensor.device_YOUR_DEVICE_ID_charge_today
    name: Charge
    type: area
    color: "#4CAF50"
    stroke_width: 2
    data_generator: |
      return (function() {
        const attr = entity.attributes.series_5min_w || [];
        const arr = typeof attr === 'string' ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) : attr;
        const now = new Date();
        const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        return arr.map(function(value, index) {
          const hours = Math.floor(index / 12);
          const minutes = (index % 12) * 5;
          const timestamp = new Date(startOfDay);
          timestamp.setHours(hours, minutes, 0, 0);
          const val = parseFloat(value) || 0;
          return [timestamp.getTime(), Math.min(Math.max(val, 0), 4000)];
        });
      })();
      - entity: sensor.device_YOUR_DEVICE_ID_discharge_today
    name: Discharge
    type: area
    color: "#FF9800"
    stroke_width: 2
    data_generator: |
      return (function() {
        const attr = entity.attributes.series_5min_w || [];
        const arr = typeof attr === 'string' ? attr.split(',').map(function(x) { return parseFloat(x.trim()) || 0; }) : attr;
        const now = new Date();
        const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        return arr.map(function(value, index) {
          const hours = Math.floor(index / 12);
          const minutes = (index % 12) * 5;
          const timestamp = new Date(startOfDay);
          timestamp.setHours(hours, minutes, 0, 0);
          const val = parseFloat(value) || 0;
          return [timestamp.getTime(), -Math.min(Math.max(val, 0), 3000)];
        });
      })();
```

### Display Checklist

- ✅ Chart type: `area` (not `column`)
- ✅ Fill opacity: Set in `apex_config.fill.opacity` (not series config)
- ✅ Y-axis title: In `apex_config.yaxis` (not top-level)
- ✅ Legend formatter: Uses `EVAL:` prefix with multi-line syntax
- ✅ Tooltip formatter: Uses `EVAL:` prefix, shows absolute values with "W" unit
- ✅ Data generator: Handles both string and array formats
- ✅ Value clamping: Applied correctly (charge: 0-4000W, discharge: -3000W to 0W)
- ✅ Timestamp calculation: Correct formula (hours = floor(index/12), minutes = (index%12)*5)
- ✅ No fixed min/max: Let ApexCharts auto-scale when data might be empty

## Version Information

- **apexcharts-card version**: 2.2.3
- **Home Assistant**: Latest (as of 2025-11-05)
- **Last updated**: 2025-11-05

