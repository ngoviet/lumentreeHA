"""Cache optimizer to normalize and minimize cache data."""
from __future__ import annotations

import logging
from typing import Dict, Any, Tuple
from datetime import datetime

from . import cache as cache_io

_LOGGER = logging.getLogger(__name__)


def is_empty_day(day_data: Dict[str, float]) -> bool:
    """Check if a day has all zero values (empty day).
    
    Args:
        day_data: Daily data dictionary
        
    Returns:
        True if all values are 0, False otherwise
    """
    # Check all key metrics
    checks = [
        float(day_data.get("pv", 0.0)) == 0.0,
        float(day_data.get("grid", 0.0)) == 0.0,
        float(day_data.get("load", 0.0)) == 0.0,
        float(day_data.get("essential", 0.0)) == 0.0,
        float(day_data.get("charge", 0.0)) == 0.0,
        float(day_data.get("discharge", 0.0)) == 0.0,
    ]
    return all(checks)


def normalize_cache(cache: Dict[str, Any], keep_coverage_range: bool = True) -> Tuple[Dict[str, Any], int, int]:
    """Normalize cache by removing empty days and optimizing structure.
    
    Args:
        cache: Cache dictionary
        keep_coverage_range: If True, keep coverage range even if days are removed
        
    Returns:
        Tuple of (normalized_cache, removed_count, kept_count)
    """
    daily = cache.get("daily", {}).copy()
    meta = cache.get("meta", {}).copy()
    empty_dates = set(meta.get("empty_dates", []))
    
    removed_count = 0
    kept_count = 0
    
    # Find earliest and latest dates with real data
    earliest_date = None
    latest_date = None
    
    # Process each day
    dates_to_remove = []
    for date_str, day_data in daily.items():
        if is_empty_day(day_data):
            # Mark as empty and remove from daily
            dates_to_remove.append(date_str)
            empty_dates.add(date_str)
            removed_count += 1
        else:
            kept_count += 1
            # Update coverage range
            if earliest_date is None or date_str < earliest_date:
                earliest_date = date_str
            if latest_date is None or date_str > latest_date:
                latest_date = date_str
    
    # Remove empty days from daily dict
    for date_str in dates_to_remove:
        daily.pop(date_str, None)
    
    # Update meta
    meta["empty_dates"] = sorted(list(empty_dates))
    
    if keep_coverage_range:
        coverage = meta.setdefault("coverage", {})
        if earliest_date:
            coverage["earliest"] = earliest_date
        if latest_date:
            coverage["latest"] = latest_date
    
    # Recompute monthly and yearly aggregates from remaining daily data
    normalized_cache = {
        "daily": daily,
        "monthly": cache.get("monthly", {}),
        "yearly_total": cache.get("yearly_total", {}),
        "meta": meta,
    }
    
    # Recompute aggregates to ensure accuracy
    normalized_cache = cache_io.recompute_aggregates(normalized_cache)
    
    return normalized_cache, removed_count, kept_count


def optimize_year_cache(device_id: str, year: int, dry_run: bool = False) -> Dict[str, Any]:
    """Optimize cache for a specific year.
    
    Args:
        device_id: Device ID
        year: Year to optimize
        dry_run: If True, don't save changes, just return stats
        
    Returns:
        Dictionary with optimization stats
    """
    cache = cache_io.load_year(device_id, year)
    
    if not cache:
        return {
            "year": year,
            "status": "no_cache",
            "removed": 0,
            "kept": 0,
            "size_before": 0,
            "size_after": 0,
        }
    
    # Calculate size before
    import json
    size_before = len(json.dumps(cache, ensure_ascii=False))
    
    # Normalize cache
    normalized_cache, removed_count, kept_count = normalize_cache(cache, keep_coverage_range=True)
    
    # Calculate size after
    size_after = len(json.dumps(normalized_cache, ensure_ascii=False))
    
    # Save if not dry run
    if not dry_run:
        cache_io.save_year(device_id, year, normalized_cache)
        _LOGGER.info(
            f"Optimized cache for {device_id}/{year}: "
            f"removed {removed_count} empty days, kept {kept_count} days, "
            f"size: {size_before} -> {size_after} bytes ({((size_before - size_after) / size_before * 100):.1f}% reduction)"
        )
    
    return {
        "year": year,
        "status": "optimized",
        "removed": removed_count,
        "kept": kept_count,
        "size_before": size_before,
        "size_after": size_after,
        "size_reduction": size_before - size_after,
        "size_reduction_percent": ((size_before - size_after) / size_before * 100) if size_before > 0 else 0.0,
    }


def optimize_all_years(device_id: str, max_years: int = 10, dry_run: bool = False) -> Dict[str, Any]:
    """Optimize cache for all years.
    
    Args:
        device_id: Device ID
        max_years: Maximum years to optimize
        dry_run: If True, don't save changes, just return stats
        
    Returns:
        Dictionary with optimization stats for all years
    """
    from datetime import date
    
    today = date.today()
    results = []
    total_removed = 0
    total_kept = 0
    total_size_before = 0
    total_size_after = 0
    
    for year_offset in range(max_years):
        year = today.year - year_offset
        if year < 2000:
            break
        
        result = optimize_year_cache(device_id, year, dry_run=dry_run)
        results.append(result)
        
        if result["status"] == "optimized":
            total_removed += result["removed"]
            total_kept += result["kept"]
            total_size_before += result["size_before"]
            total_size_after += result["size_after"]
    
    return {
        "device_id": device_id,
        "dry_run": dry_run,
        "years": results,
        "summary": {
            "total_removed": total_removed,
            "total_kept": total_kept,
            "total_size_before": total_size_before,
            "total_size_after": total_size_after,
            "total_size_reduction": total_size_before - total_size_after,
            "total_size_reduction_percent": (
                ((total_size_before - total_size_after) / total_size_before * 100) 
                if total_size_before > 0 else 0.0
            ),
        }
    }

