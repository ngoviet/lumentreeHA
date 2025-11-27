# Cache and Backfill Strategy

## Cache Structure

### File Organization
- **Daily cache**: `{device_id}/daily/{YYYY-MM-DD}.json`
- **Monthly cache**: `{device_id}/monthly/{YYYY-MM}.json`
- **Yearly cache**: `{device_id}/yearly/{YYYY}.json`

### Cache Data Format
```json
{
  "date": "2025-11-05",
  "pv": {
    "total": 12.5,
    "series_5min_w": [850, 850, 850, ...],
    "series_hour_kwh": [0.5, 0.3, 0.2, ...]
  },
  "grid": { ... },
  "battery": { ... },
  "source": "api" | "computed" | "backfill"
}
```

## Smart Backfill Strategy

### Principles
1. **Use daily API for historical data**: More reliable than monthly/yearly APIs
2. **Cache-first approach**: Check cache before API calls
3. **Incremental backfill**: Fill gaps chronologically
4. **Respect API limitations**: Don't overload API with requests

### Backfill Algorithm

#### Step 1: Detect Data Gaps
```python
async def detect_data_gaps(device_id, start_date, end_date):
    """Detect missing dates in cache."""
    gaps = []
    current_date = start_date
    
    while current_date <= end_date:
        cache_data = cache_io.load_day(device_id, current_date)
        if not cache_data or not cache_data.get("pv"):
            gaps.append(current_date)
        current_date += timedelta(days=1)
    
    return gaps
```

#### Step 2: Backfill from Daily API
```python
async def backfill_days(api_client, device_id, dates):
    """Backfill missing days from daily API."""
    for date in dates:
        try:
            data = await api_client.get_daily_stats(device_id, date)
            cache_io.save_day(device_id, date, data)
            await asyncio.sleep(0.5)  # Rate limiting
        except ApiException as e:
            _LOGGER.warning(f"Failed to backfill {date}: {e}")
            continue
```

#### Step 3: Compute Monthly/Yearly from Daily
```python
def compute_monthly_from_daily(device_id, year, month):
    """Compute monthly totals from daily cache."""
    start_date = date(year, month, 1)
    end_date = date(year, month, calendar.monthrange(year, month)[1])
    
    daily_data = []
    for day in range(1, end_date.day + 1):
        cache_date = date(year, month, day)
        daily = cache_io.load_day(device_id, cache_date)
        if daily:
            daily_data.append(daily)
    
    # Aggregate daily data into monthly
    monthly = aggregate_daily_to_monthly(daily_data)
    cache_io.save_month(device_id, year, month, monthly)
```

### Handling API Limitations

#### Problem: Monthly/Yearly API Only Returns Current Period
- **Symptom**: `getYearData(year=2024)` returns 2025 data
- **Solution**: Only use API for current year/month, compute historical from daily cache

```python
async def get_year_data(api_client, device_id, year):
    """Get year data with fallback to daily cache."""
    today = date.today()
    current_year = today.year
    
    if year == current_year:
        # Use API for current year
        return await api_client.get_year_data(device_id, year)
    else:
        # Compute from daily cache for historical years
        return compute_yearly_from_daily(device_id, year)
```

## Cache Management

### Cache Validation
```python
def is_cache_valid(cache_data, max_age_hours=24):
    """Check if cache is still valid."""
    if not cache_data:
        return False
    
    cache_time = cache_data.get("cache_time")
    if not cache_time:
        return False
    
    age = (datetime.now() - cache_time).total_seconds() / 3600
    return age < max_age_hours
```

### Cache Purge
```python
def purge_old_cache(device_id, keep_days=90):
    """Remove cache files older than keep_days."""
    cache_dir = get_cache_dir(device_id, "daily")
    cutoff_date = date.today() - timedelta(days=keep_days)
    
    for cache_file in cache_dir.glob("*.json"):
        file_date = parse_date_from_filename(cache_file)
        if file_date < cutoff_date:
            cache_file.unlink()
```

### Cache Optimization
1. **Compress data**: Store only essential fields
2. **Batch writes**: Write multiple days at once
3. **Index files**: Create index for fast lookups
4. **Lazy loading**: Load cache only when needed

## Data Processing

### Converting 5-minute Series to Hourly
```python
def series_5min_to_hourly(series_5min_kwh):
    """Convert 5-minute kWh series to hourly totals."""
    hourly = []
    for hour in range(24):
        start_idx = hour * 12
        end_idx = start_idx + 12
        hour_total = sum(series_5min_kwh[start_idx:end_idx])
        hourly.append(hour_total)
    return hourly
```

### Converting to Watt
```python
def kwh_to_watt(kwh_value, interval_minutes=5):
    """Convert kWh to Watt for given interval."""
    # kWh → W = (kWh * 1000) / (hours)
    # For 5-minute interval: (kWh * 1000) / (5/60) = kWh * 12000
    # For hourly: (kWh * 1000) / 1 = kWh * 1000
    hours = interval_minutes / 60.0
    return (kwh_value * 1000.0) / hours
```

### Battery Data Processing
```python
def process_battery_data(battery_series_5min_w):
    """Split battery series into charge and discharge."""
    charge = [w if w > 0 else 0.0 for w in battery_series_5min_w]
    discharge = [(-w) if w < 0 else 0.0 for w in battery_series_5min_w]
    return charge, discharge
```

## Best Practices

1. **Always cache API responses**: Reduce API calls
2. **Validate cache before use**: Check data structure and age
3. **Use daily API for historical**: More reliable than monthly/yearly
4. **Compute aggregates from daily**: Don't trust monthly/yearly APIs for historical
5. **Implement rate limiting**: Don't overload API
6. **Handle missing data gracefully**: Use defaults or skip
7. **Monitor cache size**: Purge old data periodically
8. **Backfill incrementally**: Start from oldest gaps

## Troubleshooting

### Issue: Cache Not Updating
- **Check**: Cache file permissions
- **Check**: Cache directory exists
- **Solution**: Clear cache and re-fetch

### Issue: Backfill Too Slow
- **Check**: API rate limiting
- **Solution**: Increase delay between requests
- **Solution**: Batch backfill in background

### Issue: Monthly/Yearly Data Incorrect
- **Check**: API limitations (may only return current period)
- **Solution**: Compute from daily cache instead
- **Solution**: Verify aggregation logic


