"""Simple JSON cache for Lumentree statistics.

Cache layout per device/year:
  .storage/lumentree_stats/{device_id}/{year}.json

Structure:
{
  "daily": {"YYYY-MM-DD": {"pv": 0.0, "grid": 0.0, "load": 0.0, "essential": 0.0, "charge": 0.0, "discharge": 0.0}},
  "monthly": {
    "pv": [12 floats], "grid": [...], "load": [...], "essential": [...], "charge": [...], "discharge": [...]
  },
  "yearly_total": {"pv": 0.0, "grid": 0.0, "load": 0.0, "essential": 0.0, "charge": 0.0, "discharge": 0.0},
  "meta": {"version": 1, "last_backfill_date": "YYYY-MM-DD"}
}
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Dict, Any, Tuple

from ..const import DEFAULT_TARIFF_VND_PER_KWH

_LOGGER = logging.getLogger(__name__)

CACHE_BASE_DIR = os.path.join(".storage", "lumentree_stats")

_MONTHLY_KEYS = ("pv", "grid", "load", "essential", "total_load", "charge", "discharge", "saved_kwh", "savings_vnd")


def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _empty_month() -> list[float]:
    return [0.0 for _ in range(12)]


def _empty_cache() -> Dict[str, Any]:
    return {
        "daily": {},
        "monthly": {
            "pv": _empty_month(),
            "grid": _empty_month(),
            "load": _empty_month(),
            "essential": _empty_month(),
            "total_load": _empty_month(),
            "charge": _empty_month(),
            "discharge": _empty_month(),
            "saved_kwh": _empty_month(),
            "savings_vnd": _empty_month(),
        },
        "yearly_total": {"pv": 0.0, "grid": 0.0, "load": 0.0, "essential": 0.0, "total_load": 0.0, "charge": 0.0, "discharge": 0.0, "saved_kwh": 0.0, "savings_vnd": 0.0},
        "meta": {
            "version": 1,
            "last_backfill_date": None,
            # Phạm vi đã có dữ liệu (bao phủ)
            "coverage": {"earliest": None, "latest": None},
            # Những ngày được xác nhận rỗng (để bỏ qua vĩnh viễn)
            "empty_dates": [],
        },
    }


def cache_path(device_id: str, year: int) -> str:
    dev_dir = os.path.join(CACHE_BASE_DIR, device_id)
    _ensure_dir(dev_dir)
    return os.path.join(dev_dir, f"{year}.json")


def _needs_recompute(cache: Dict[str, Any]) -> bool:
    """Check if cache needs recompute based on monthly arrays consistency.
    
    Returns True if monthly arrays appear incorrect (all values same or missing).
    """
    if not cache.get("daily"):
        return False
    
    monthly = cache.get("monthly", {})
    if not monthly:
        return True
    
    # Check if monthly arrays have valid data
    # If all months (except last) have same value, likely needs recompute
    for key in ["pv", "grid", "load"]:
        if key not in monthly:
            return True
        arr = monthly[key]
        if not isinstance(arr, list) or len(arr) != 12:
            return True
        # Check if first 11 months all have same value (likely incorrect)
        if len(set(arr[:11])) <= 1 and arr[0] != 0.0:
            return True
    
    return False


def load_year(device_id: str, year: int, auto_recompute: bool = True) -> Dict[str, Any]:
    """Load cache for a year, optionally auto-recomputing aggregates if needed.
    
    Args:
        device_id: Device ID
        year: Year to load
        auto_recompute: If True, automatically recompute aggregates if they appear incorrect
        
    Returns:
        Cache dictionary
    """
    path = cache_path(device_id, year)
    if not os.path.exists(path):
        return _empty_cache()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return _empty_cache()
            
            # Auto-recompute if monthly arrays appear incorrect
            if auto_recompute and _needs_recompute(data):
                

                _LOGGER.info(f"Auto-recomputing aggregates for {device_id}/{year} (monthly arrays appear incorrect)")
                data = recompute_aggregates(data)
                # Save recomputed cache
                try:
                    save_year(device_id, year, data)
                except Exception:
                    pass  # Best effort save
            
            return data
    except Exception:
        return _empty_cache()


def save_year(device_id: str, year: int, data: Dict[str, Any]) -> None:
    """Save cache atomically (write to temp file then rename)."""
    path = cache_path(device_id, year)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)  # atomic on Linux/Unix
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        pass


def update_daily(
    cache: Dict[str, Any], date_str: str, values: Dict[str, float]
) -> Tuple[Dict[str, Any], int]:
    """Update one day in cache using incremental month/year updates (O(1)).

    Returns (cache, month_index)
    """
    load_value = float(values.get("load", 0.0))
    essential_value = float(values.get("essential", 0.0))
    total_load_value = round(load_value + essential_value, 1)
    grid_value = float(values.get("grid", 0.0))
    saved_kwh = max(0.0, total_load_value - grid_value)
    savings_vnd = saved_kwh * DEFAULT_TARIFF_VND_PER_KWH

    daily = cache.setdefault("daily", {})
    old_entry = daily.get(date_str, {})

    new_entry = {
        "pv": round(float(values.get("pv", 0.0)), 1),
        "grid": round(grid_value, 1),
        "load": round(load_value, 1),
        "essential": round(essential_value, 1),
        "total_load": total_load_value,
        "charge": round(float(values.get("charge", 0.0)), 1),
        "discharge": round(float(values.get("discharge", 0.0)), 1),
        "saved_kwh": round(saved_kwh, 1),
        "savings_vnd": round(savings_vnd, 0),
    }
    daily[date_str] = new_entry

    # Update coverage
    meta = cache.setdefault("meta", {})
    cov = meta.setdefault("coverage", {"earliest": None, "latest": None})
    try:
        if cov["earliest"] is None or date_str < cov["earliest"]:
            cov["earliest"] = date_str
        if cov["latest"] is None or date_str > cov["latest"]:
            cov["latest"] = date_str
    except Exception:
        pass
    try:
        empties = set(meta.setdefault("empty_dates", []))
        if date_str in empties:
            empties.discard(date_str)
            meta["empty_dates"] = sorted(list(empties))
    except Exception:
        pass

    try:
        month = int(date_str[5:7])
    except Exception:
        month = 1
    m_idx = month - 1

    # Incremental month update: subtract old, add new
    monthly = cache.setdefault("monthly", {})
    yearly = cache.setdefault("yearly_total", {})
    for key in _MONTHLY_KEYS:
        if key not in monthly:
            monthly[key] = _empty_month()
        old_val = float(old_entry.get(key, 0.0)) if old_entry else 0.0
        new_val = float(new_entry[key])
        delta = new_val - old_val
        # Update month bucket
        if key == "savings_vnd":
            monthly[key][m_idx] = round(monthly[key][m_idx] + delta, 0)
            yearly[key] = round(yearly.get(key, 0.0) + delta, 0)
        else:
            monthly[key][m_idx] = round(monthly[key][m_idx] + delta, 1)
            yearly[key] = round(yearly.get(key, 0.0) + delta, 1)

    return cache, m_idx


def mark_empty(cache: Dict[str, Any], date_str: str) -> Dict[str, Any]:
    """Đánh dấu một ngày là rỗng để bỏ qua khi backfill/gap-fill.

    Không lưu daily cho ngày rỗng, chỉ ghi chú trong meta.empty_dates.
    """
    meta = cache.setdefault("meta", {})
    empties = set(meta.setdefault("empty_dates", []))
    empties.add(date_str)
    meta["empty_dates"] = sorted(list(empties))
    return cache


def _get_total_load(data: dict[str, float]) -> float:
    """DEPRECATED: Calculate total_load from load + essential. Not used internally."""
    if "total_load" in data:
        return float(data.get("total_load", 0.0))
    return float(data.get("load", 0.0)) + float(data.get("essential", 0.0))


def summarize_month(cache: Dict[str, Any], month: int) -> Dict[str, float]:
    idx = month - 1
    m = cache.get("monthly", {})
    load_val = float(m.get("load", _empty_month())[idx])
    essential_val = float(m.get("essential", _empty_month())[idx])
    # Try to get total_load, fallback to calculating from load + essential
    total_load_val = float(m.get("total_load", [0.0] * 12)[idx])
    if total_load_val == 0.0 and (load_val != 0.0 or essential_val != 0.0):
        # Old data: calculate from load + essential
        total_load_val = round(load_val + essential_val, 1)
    return {
        "pv": round(float(m.get("pv", _empty_month())[idx]), 1),
        "grid": round(float(m.get("grid", _empty_month())[idx]), 1),
        "load": round(load_val, 1),
        "essential": round(essential_val, 1),
        "total_load": round(total_load_val, 1),
        "charge": round(float(m.get("charge", _empty_month())[idx]), 1),
        "discharge": round(float(m.get("discharge", _empty_month())[idx]), 1),
        "saved_kwh": round(float(m.get("saved_kwh", _empty_month())[idx]), 1),
        "savings_vnd": round(float(m.get("savings_vnd", _empty_month())[idx]), 0),
    }


def summarize_year(cache: Dict[str, Any]) -> Dict[str, float]:
    """Summarize year totals, with backward compatibility for old data without total_load."""
    yearly_total = cache.get("yearly_total", {})
    result = {k: float(v) for k, v in yearly_total.items()}
    
    # Backward compatibility: calculate total_load if missing
    if "total_load" not in yearly_total or result.get("total_load", 0.0) == 0.0:
        load_val = result.get("load", 0.0)
        essential_val = result.get("essential", 0.0)
        if load_val != 0.0 or essential_val != 0.0:
            result["total_load"] = round(load_val + essential_val, 1)
    
    return result


def recompute_aggregates(cache: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild monthly arrays and yearly totals from daily map."""
    monthly = {
        "pv": _empty_month(),
        "grid": _empty_month(),
        "load": _empty_month(),
        "essential": _empty_month(),
        "total_load": _empty_month(),
        "charge": _empty_month(),
        "discharge": _empty_month(),
        "saved_kwh": _empty_month(),
        "savings_vnd": _empty_month(),
    }
    for d, v in cache.get("daily", {}).items():
        try:
            month = int(d[5:7]) - 1
        except Exception:
            continue
        for key in monthly.keys():
            if key == "total_load":
                # Calculate total_load from load + essential if not already stored
                # Use stored total_load if available, otherwise calculate from load + essential
                stored_total = v.get("total_load")
                if stored_total is not None:
                    monthly[key][month] += float(stored_total)
                else:
                    load_val = float(v.get("load", 0.0))
                    essential_val = float(v.get("essential", 0.0))
                    monthly[key][month] += round(load_val + essential_val, 1)
            elif key == "saved_kwh":
                # Calculate saved_kwh from total_load - grid if not already stored
                total_load_val = float(v.get("total_load", float(v.get("load", 0.0)) + float(v.get("essential", 0.0))))
                grid_val = float(v.get("grid", 0.0))
                saved_kwh_val = max(0.0, total_load_val - grid_val)
                monthly[key][month] += saved_kwh_val
            elif key == "savings_vnd":
                # Calculate savings_vnd from saved_kwh if not already stored
                total_load_val = float(v.get("total_load", float(v.get("load", 0.0)) + float(v.get("essential", 0.0))))
                grid_val = float(v.get("grid", 0.0))
                saved_kwh_val = max(0.0, total_load_val - grid_val)
                monthly[key][month] += saved_kwh_val * DEFAULT_TARIFF_VND_PER_KWH
            else:
                monthly[key][month] += float(v.get(key, 0.0))
    # Round monthly arrays to match API precision
    cache["monthly"] = {}
    for k, vals in monthly.items():
        if k == "savings_vnd":
            cache["monthly"][k] = [round(x, 0) for x in vals]
        else:
            cache["monthly"][k] = [round(x, 1) for x in vals]

    # Round yearly totals to match API precision
    ytot = {}
    for k, vals in cache["monthly"].items():
        s = sum(vals)
        if k == "savings_vnd":
            ytot[k] = round(s, 0)
        else:
            ytot[k] = round(s, 1)
    cache["yearly_total"] = ytot
    return cache


def purge_year(device_id: str, year: int) -> bool:
    path = cache_path(device_id, year)
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def purge_device(device_id: str) -> bool:
    """Purge all cache files for a device."""
    dev_dir = os.path.join(CACHE_BASE_DIR, device_id)
    try:
        if os.path.isdir(dev_dir):
            files_deleted = 0
            for f in os.listdir(dev_dir):
                try:
                    file_path = os.path.join(dev_dir, f)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        files_deleted += 1
                except Exception as e:
                    _LOGGER.warning("Failed to delete %s: %s", f, e)
            # Keep directory for future use, don't rmdir
            return files_deleted > 0
    except Exception as e:
        _LOGGER.error("Failed to purge device cache: %s", e)
    return False


