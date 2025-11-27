"""Smart backfill system using getYearData/getMonthData for optimal performance."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Dict, Any, List, Tuple, Optional
import time

from . import cache as cache_io
from ..core.api_client import LumentreeHttpApiClient

_LOGGER = logging.getLogger(__name__)


async def detect_data_gaps_from_api(
    api_client: LumentreeHttpApiClient,
    device_id: str,
    max_years: int = 10
) -> Dict[int, List[int]]:
    """Detect which months have data using getYearData API (fast scan).
    
    Args:
        api_client: API client
        device_id: Device ID
        max_years: Maximum years to check
        
    Returns:
        Dictionary mapping year to list of months (1-12) that have data
    """
    today = dt.date.today()
    years_with_data: Dict[int, List[int]] = {}
    
    for year_offset in range(max_years):
        year = today.year - year_offset
        if year < 2000:
            break
        
        try:
            year_data = await api_client.get_year_data(device_id, year)
            
            # Check which months have data
            months_with_data = []
            pv_data = year_data.get("pv", [0.0] * 12)
            grid_data = year_data.get("grid", [0.0] * 12)
            load_data = year_data.get("homeload", [0.0] * 12)
            
            for month_idx in range(12):
                month = month_idx + 1
                has_data = (
                    pv_data[month_idx] > 0.0 or
                    grid_data[month_idx] > 0.0 or
                    load_data[month_idx] > 0.0
                )
                if has_data:
                    months_with_data.append(month)
            
            if months_with_data:
                years_with_data[year] = months_with_data
                _LOGGER.debug(f"Year {year} has data in months: {months_with_data}")
        except Exception as err:
            _LOGGER.debug(f"Error checking year {year} from API: {err}")
            continue
    
    return years_with_data


async def backfill_month_from_api(
    api_client: LumentreeHttpApiClient,
    device_id: str,
    year: int,
    month: int,
    cache: Dict[str, Any]
) -> Tuple[int, int]:
    """Backfill a month using getMonthData API (much faster than daily).
    
    Args:
        api_client: API client
        device_id: Device ID
        year: Year
        month: Month (1-12)
        cache: Cache dictionary to update
        
    Returns:
        Tuple of (days_added, days_updated)
    """
    try:
        month_data = await api_client.get_month_data(device_id, year, month)
        
        # Get daily arrays from API
        pv_daily = month_data.get("pv", [])
        grid_daily = month_data.get("grid", [])
        load_daily = month_data.get("homeload", [])
        essential_daily = month_data.get("essentialLoad", [])
        bat_daily = month_data.get("bat", [])
        batf_daily = month_data.get("batF", [])
        
        days_added = 0
        days_updated = 0
        
        # Get number of days in month
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        
        # Process each day
        daily = cache.setdefault("daily", {})
        for day in range(1, min(len(pv_daily), days_in_month) + 1):
            date_str = f"{year}-{month:02d}-{day:02d}"
            
            # Check if day already exists and has data
            existing = daily.get(date_str)
            if existing:
                # Check if existing has real data
                has_existing_data = any(
                    float(existing.get(key, 0.0)) > 0.0
                    for key in ["pv", "grid", "load", "essential"]
                )
                
                # Check if API has data for this day
                has_api_data = (
                    day <= len(pv_daily) and pv_daily[day - 1] > 0.0 or
                    day <= len(grid_daily) and grid_daily[day - 1] > 0.0 or
                    day <= len(load_daily) and load_daily[day - 1] > 0.0
                )
                
                # Only update if API has data and existing doesn't
                if has_api_data and not has_existing_data:
                    days_updated += 1
                else:
                    continue  # Skip if already has data
            else:
                days_added += 1
            
            # Extract values for this day
            pv_val = pv_daily[day - 1] if day <= len(pv_daily) else 0.0
            grid_val = grid_daily[day - 1] if day <= len(grid_daily) else 0.0
            load_val = load_daily[day - 1] if day <= len(load_daily) else 0.0
            essential_val = essential_daily[day - 1] if day <= len(essential_daily) else 0.0
            charge_val = bat_daily[day - 1] if day <= len(bat_daily) else 0.0
            discharge_val = batf_daily[day - 1] if day <= len(batf_daily) else 0.0
            
            # Calculate derived values
            total_load_val = round(load_val + essential_val, 1)
            saved_kwh = max(0.0, total_load_val - grid_val)
            from ..const import DEFAULT_TARIFF_VND_PER_KWH
            savings_vnd = round(saved_kwh * DEFAULT_TARIFF_VND_PER_KWH, 0)
            
            # Update cache
            daily[date_str] = {
                "pv": round(pv_val, 1),
                "grid": round(grid_val, 1),
                "load": round(load_val, 1),
                "essential": round(essential_val, 1),
                "total_load": total_load_val,
                "charge": round(charge_val, 1),
                "discharge": round(discharge_val, 1),
                "saved_kwh": round(saved_kwh, 1),
                "savings_vnd": savings_vnd,
            }
        
        return days_added, days_updated
    except Exception as err:
        _LOGGER.error(f"Error backfilling month {year}-{month:02d}: {err}")
        return 0, 0


async def smart_backfill(
    hass,
    aggregator,
    max_years: int = 10,
    optimize_cache: bool = True
) -> Dict[str, Any]:
    """Smart backfill using getYearData/getMonthData APIs for optimal performance.
    
    Strategy:
    1. Use getYearData to quickly identify which years/months have data
    2. Use getMonthData to backfill months that have data (much faster than daily)
    3. Only backfill missing days, skip if already has data
    4. Auto-optimize cache after backfill
    
    Args:
        hass: HomeAssistant instance
        aggregator: StatsAggregator instance
        max_years: Maximum years to backfill
        optimize_cache: If True, optimize cache after backfill
        
    Returns:
        Dictionary with backfill statistics
    """
    device_id = aggregator._device_id
    api_client = aggregator._api
    
    start_time = time.time()
    stats = {
        "years_processed": 0,
        "months_processed": 0,
        "days_added": 0,
        "days_updated": 0,
        "years_with_data": [],
        "errors": 0,
    }
    
    _LOGGER.info(f"Starting smart backfill for device {device_id} (max_years={max_years})")
    
    # Step 1: Quick scan - identify years/months with data using getYearData
    _LOGGER.info("Step 1: Scanning years with data using getYearData API...")
    years_with_data = await detect_data_gaps_from_api(api_client, device_id, max_years)
    
    stats["years_with_data"] = list(years_with_data.keys())
    _LOGGER.info(f"Found data in {len(years_with_data)} years: {list(years_with_data.keys())}")
    
    # Step 2: Backfill months that have data using getMonthData
    _LOGGER.info("Step 2: Backfilling months with data using getMonthData API...")
    
    for year, months in sorted(years_with_data.items(), reverse=True):
        _LOGGER.info(f"Processing year {year} ({len(months)} months with data)")
        
        # Load cache for this year
        cache = await hass.async_add_executor_job(cache_io.load_year, device_id, year)
        cache_dirty = False
        
        for month in sorted(months):
            try:
                days_added, days_updated = await backfill_month_from_api(
                    api_client, device_id, year, month, cache
                )
                
                if days_added > 0 or days_updated > 0:
                    cache_dirty = True
                    stats["days_added"] += days_added
                    stats["days_updated"] += days_updated
                    stats["months_processed"] += 1
                    _LOGGER.debug(
                        f"Month {year}-{month:02d}: added {days_added}, updated {days_updated}"
                    )
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)
            except Exception as err:
                _LOGGER.error(f"Error backfilling {year}-{month:02d}: {err}")
                stats["errors"] += 1
        
        # Save cache if modified
        if cache_dirty:
            # Recompute aggregates
            cache = cache_io.recompute_aggregates(cache)
            await hass.async_add_executor_job(cache_io.save_year, device_id, year, cache)
            stats["years_processed"] += 1
            _LOGGER.info(f"Saved cache for year {year}")
    
    # Step 3: Optimize cache if requested
    if optimize_cache:
        _LOGGER.info("Step 3: Optimizing cache...")
        try:
            from . import cache_optimizer
            for year in stats["years_with_data"]:
                result = await hass.async_add_executor_job(
                    cache_optimizer.optimize_year_cache, device_id, year, False
                )
                if result["status"] == "optimized":
                    _LOGGER.info(
                        f"Optimized year {year}: removed {result['removed']} empty days, "
                        f"size reduction: {result['size_reduction_percent']:.1f}%"
                    )
        except Exception as err:
            _LOGGER.warning(f"Error optimizing cache: {err}")
    
    elapsed = time.time() - start_time
    stats["elapsed_seconds"] = round(elapsed, 2)
    
    _LOGGER.info(
        f"Smart backfill completed: {stats['years_processed']} years, "
        f"{stats['months_processed']} months, {stats['days_added']} days added, "
        f"{stats['days_updated']} days updated, {stats['errors']} errors, "
        f"took {elapsed:.1f}s"
    )
    
    return stats

