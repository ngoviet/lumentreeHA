"""
Migration utility to backfill total_load field in old cache data.

This script can be run manually to migrate old cache data that doesn't have
the total_load field. It calculates total_load = load + essential for all
historical data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

_LOGGER = logging.getLogger(__name__)


def migrate_cache_file(cache_path: Path) -> bool:
    """Migrate a single cache file to include total_load field.
    
    Args:
        cache_path: Path to the cache JSON file
        
    Returns:
        True if migration was needed and performed, False otherwise
    """
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        modified = False
        
        # Migrate daily data
        daily = data.get("daily", {})
        for date_str, day_data in daily.items():
            if "total_load" not in day_data:
                load_val = float(day_data.get("load", 0.0))
                essential_val = float(day_data.get("essential", 0.0))
                day_data["total_load"] = load_val + essential_val
                modified = True
                _LOGGER.debug(f"Migrated daily {date_str}: total_load = {day_data['total_load']}")
        
        # Migrate monthly arrays
        monthly = data.get("monthly", {})
        if "total_load" not in monthly:
            # Create total_load monthly array from load + essential
            load_monthly = monthly.get("load", [0.0] * 12)
            essential_monthly = monthly.get("essential", [0.0] * 12)
            total_load_monthly = [
                float(load_monthly[i]) + float(essential_monthly[i])
                for i in range(12)
            ]
            monthly["total_load"] = total_load_monthly
            modified = True
            _LOGGER.debug(f"Migrated monthly arrays")
        
        # Migrate yearly_total
        yearly_total = data.get("yearly_total", {})
        if "total_load" not in yearly_total:
            load_val = float(yearly_total.get("load", 0.0))
            essential_val = float(yearly_total.get("essential", 0.0))
            yearly_total["total_load"] = load_val + essential_val
            modified = True
            _LOGGER.debug(f"Migrated yearly_total: total_load = {yearly_total['total_load']}")
        
        if modified:
            # Backup original file
            backup_path = cache_path.with_suffix('.json.backup')
            if not backup_path.exists():
                with open(backup_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                _LOGGER.info(f"Created backup: {backup_path}")
            
            # Write migrated data
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            _LOGGER.info(f"✅ Migrated {cache_path}")
            return True
        
        return False
        
    except Exception as e:
        _LOGGER.error(f"Error migrating {cache_path}: {e}")
        return False


def migrate_all_cache(device_id: str, base_path: Path | None = None) -> int:
    """Migrate all cache files for a device.
    
    Args:
        device_id: Device serial number
        base_path: Base path to cache directory (default: .storage/lumentree_stats)
        
    Returns:
        Number of files migrated
    """
    if base_path is None:
        base_path = Path(".storage/lumentree_stats")
    
    device_path = base_path / device_id
    if not device_path.exists():
        _LOGGER.warning(f"Cache directory not found: {device_path}")
        return 0
    
    migrated_count = 0
    
    # Find all year cache files
    for year_file in device_path.glob("*.json"):
        if year_file.name.endswith('.backup'):
            continue
        
        if migrate_cache_file(year_file):
            migrated_count += 1
    
    _LOGGER.info(f"Migration complete: {migrated_count} files migrated for {device_id}")
    return migrated_count

