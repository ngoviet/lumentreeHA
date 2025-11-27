"""Utilities to detect when device first has data."""
from __future__ import annotations

import datetime as dt
from typing import Dict, Any, Optional, Tuple
import logging

from . import cache as cache_io

_LOGGER = logging.getLogger(__name__)


def find_earliest_data_from_cache(
    device_id: str, 
    max_years: int = 10
) -> Optional[Tuple[str, int, int]]:
    """Find earliest date with real data from cache.
    
    Args:
        device_id: Device ID
        max_years: Maximum years to look back
        
    Returns:
        Tuple of (date_str, year, month) or None if no data found
        date_str format: YYYY-MM-DD
    """
    today = dt.date.today()
    earliest_date = None
    earliest_year = None
    earliest_month = None
    
    # Check all years (API filtering is done separately in find_earliest_data_date)
    years_to_check = [today.year - i for i in range(max_years) if today.year - i >= 2000]
    
    # Scan years for earliest date with data
    for year in years_to_check:
        cache = cache_io.load_year(device_id, year)
        daily = cache.get("daily", {})
        
        if not daily:
            continue
        
        # Find earliest date with real data (not all zeros)
        for date_str in sorted(daily.keys()):
            day_data = daily[date_str]
            
            # Check if has real data (at least one value > 0)
            has_data = any(
                float(day_data.get(key, 0.0)) > 0.0
                for key in ["pv", "grid", "load", "essential", "charge", "discharge"]
            )
            
            if has_data:
                try:
                    year_val = int(date_str[:4])
                    month_val = int(date_str[5:7])
                    
                    if earliest_date is None or date_str < earliest_date:
                        earliest_date = date_str
                        earliest_year = year_val
                        earliest_month = month_val
                except (ValueError, IndexError):
                    continue
    
    if earliest_date:
        return (earliest_date, earliest_year, earliest_month)
    return None


async def find_earliest_data_from_api(api_client, device_id: str, max_years: int = 10) -> Optional[Tuple[int, int]]:
    """Find earliest month with data from getYearData API.
    
    Uses getYearData API to quickly scan years and find earliest month with data.
    This is much faster than checking daily data.
    
    Args:
        api_client: LumentreeHttpApiClient instance
        device_id: Device ID
        max_years: Maximum years to look back
        
    Returns:
        Tuple of (year, month) or None if no data found
        month: 1-12
    """
    today = dt.date.today()
    earliest_year = None
    earliest_month = None
    
    # Scan years from most recent to oldest
    for year_offset in range(max_years):
        year = today.year - year_offset
        if year < 2000:  # Safety limit
            break
        
        try:
            # Get year data from API (one call per year - very fast)
            year_data = await api_client.get_year_data(device_id, year)
            
            # Check each month for data (scan 12 months in memory - instant)
            pv_data = year_data.get("pv", [0.0] * 12)
            grid_data = year_data.get("grid", [0.0] * 12)
            load_data = year_data.get("homeload", [0.0] * 12)
            
            # Scan months from January to December
            for month_idx in range(12):
                month = month_idx + 1
                
                # Check if has real data (any value > 0)
                has_data = (
                    pv_data[month_idx] > 0.0 or
                    grid_data[month_idx] > 0.0 or
                    load_data[month_idx] > 0.0
                )
                
                if has_data:
                    # Update earliest if this is earlier
                    if earliest_year is None or year < earliest_year or (year == earliest_year and month < earliest_month):
                        earliest_year = year
                        earliest_month = month
            
            # If we found data in this year, we can stop early (years are scanned newest to oldest)
            # But we need to continue to find the earliest year, so we don't stop here
        except Exception as err:
            _LOGGER.debug(f"Error checking year {year} from API: {err}")
            continue
    
    if earliest_year and earliest_month:
        return (earliest_year, earliest_month)
    return None


async def find_earliest_data_date(
    hass,
    aggregator,
    prefer_api: bool = True,
    use_api_filter: bool = True
) -> Optional[Dict[str, Any]]:
    """Find earliest date when device has data.
    
    Uses optimized algorithm:
    1. First, use getYearData API to quickly scan years and find months with data
    2. Then, optionally use API to filter which years to check in cache
    3. Finally, check cache for exact day-level precision
    
    Args:
        hass: HomeAssistant instance
        aggregator: StatsAggregator instance
        prefer_api: If True, prefer API data (more comprehensive)
        use_api_filter: If True, use API to filter years before checking cache (faster)
        
    Returns:
        Dictionary with:
        {
            "date": "YYYY-MM-DD",
            "year": int,
            "month": int,
            "source": "cache" or "api",
            "method": "daily" or "monthly"
        }
        or None if no data found
    """
    device_id = aggregator._device_id
    api_client = aggregator._api
    
    # Step 1: Quick scan using API (getYearData) to find years/months with data
    # This is MUCH faster than checking daily data
    api_result = None
    if prefer_api:
        try:
            api_result = await find_earliest_data_from_api(api_client, device_id, 10)
            _LOGGER.debug(f"API scan found earliest: {api_result}")
        except Exception as err:
            _LOGGER.warning(f"Error finding earliest data from API: {err}")
    
    # Step 2: Check cache for exact day-level precision
    # If we have API result, we can optimize by only checking that year and earlier
    # But for simplicity, we check all years (cache is fast enough)
    cache_result = None
    try:
        cache_result = await hass.async_add_executor_job(
            find_earliest_data_from_cache, device_id, 10
        )
    except Exception as err:
        _LOGGER.warning(f"Error finding earliest data from cache: {err}")
    
    # Compare results
    if api_result and cache_result:
        api_year, api_month = api_result
        cache_date, cache_year, cache_month = cache_result
        
        # API gives month-level precision, cache gives day-level
        # Use API if it's earlier or same year/month
        if api_year < cache_year or (api_year == cache_year and api_month < cache_month):
            # Use first day of API month
            earliest_date = f"{api_year}-{api_month:02d}-01"
            return {
                "date": earliest_date,
                "year": api_year,
                "month": api_month,
                "source": "api",
                "method": "monthly"
            }
        else:
            return {
                "date": cache_date,
                "year": cache_year,
                "month": cache_month,
                "source": "cache",
                "method": "daily"
            }
    elif api_result:
        api_year, api_month = api_result
        earliest_date = f"{api_year}-{api_month:02d}-01"
        return {
            "date": earliest_date,
            "year": api_year,
            "month": api_month,
            "source": "api",
            "method": "monthly"
        }
    elif cache_result:
        cache_date, cache_year, cache_month = cache_result
        return {
            "date": cache_date,
            "year": cache_year,
            "month": cache_month,
            "source": "cache",
            "method": "daily"
        }
    
    return None

