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
import os
from typing import Dict, Any, Tuple


CACHE_BASE_DIR = os.path.join(".storage", "lumentree_stats")


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


def load_year(device_id: str, year: int) -> Dict[str, Any]:
    path = cache_path(device_id, year)
    if not os.path.exists(path):
        return _empty_cache()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else _empty_cache()
    except Exception:
        return _empty_cache()


def save_year(device_id: str, year: int, data: Dict[str, Any]) -> None:
    path = cache_path(device_id, year)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def update_daily(
    cache: Dict[str, Any], date_str: str, values: Dict[str, float]
) -> Tuple[Dict[str, Any], int, int]:
    """Update one day in cache and recompute its month index.

    Returns (cache, month_index, year_changed_flag)
    """
    # Store daily - API returns integers divided by 10, so precision is 1 decimal place for kWh
    load_value = float(values.get("load", 0.0))
    essential_value = float(values.get("essential", 0.0))
    # Calculate total_load from raw values, then round to match API precision (1 decimal)
    total_load_value = round(load_value + essential_value, 1)
    grid_value = float(values.get("grid", 0.0))
    # Calculate savings: saved_kwh = total_load - grid_in, savings_vnd = saved_kwh * tariff
    saved_kwh = max(0.0, total_load_value - grid_value)
    from ..const import DEFAULT_TARIFF_VND_PER_KWH
    savings_vnd = saved_kwh * DEFAULT_TARIFF_VND_PER_KWH
    cache.setdefault("daily", {})[date_str] = {
        "pv": round(float(values.get("pv", 0.0)), 1),  # API precision: 1 decimal
        "grid": round(grid_value, 1),
        "load": round(load_value, 1),
        "essential": round(essential_value, 1),
        "total_load": total_load_value,  # Already rounded above
        "charge": round(float(values.get("charge", 0.0)), 1),
        "discharge": round(float(values.get("discharge", 0.0)), 1),
        "saved_kwh": round(saved_kwh, 1),
        "savings_vnd": round(savings_vnd, 0),  # Money: no decimals
    }

    # Update coverage and remove date from empty_dates if present
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

    # Month index from date_str
    # date_str format: YYYY-MM-DD
    try:
        month = int(date_str[5:7])
    except Exception:
        month = 1
    m_idx = month - 1

    # Recompute that month bucket from daily
    monthly = cache.setdefault("monthly", {})
    for key in ("pv", "grid", "load", "essential", "total_load", "charge", "discharge", "saved_kwh", "savings_vnd"):
        if key not in monthly:
            monthly[key] = _empty_month()
        # sum all days of the month - round to 1 decimal for kWh, 0 for VND
        s = 0.0
        for d, v in cache["daily"].items():
            try:
                if int(d[5:7]) == month:
                    s += float(v.get(key, 0.0))
            except Exception:
                continue
        # Round based on key type: 1 decimal for kWh, 0 for VND
        if key == "savings_vnd":
            monthly[key][m_idx] = round(s, 0)
        else:
            monthly[key][m_idx] = round(s, 1)

    # Recompute yearly totals - round to match API precision
    ytot = cache.setdefault("yearly_total", {})
    for key in ("pv", "grid", "load", "essential", "total_load", "charge", "discharge", "saved_kwh", "savings_vnd"):
        s = sum(monthly.get(key, _empty_month()))
        # Round based on key type: 1 decimal for kWh, 0 for VND
        if key == "savings_vnd":
            ytot[key] = round(s, 0)
        else:
            ytot[key] = round(s, 1)

    return cache, m_idx, 1


def mark_empty(cache: Dict[str, Any], date_str: str) -> Dict[str, Any]:
    """Đánh dấu một ngày là rỗng để bỏ qua khi backfill/gap-fill.

    Không lưu daily cho ngày rỗng, chỉ ghi chú trong meta.empty_dates.
    """
    meta = cache.setdefault("meta", {})
    empties = set(meta.setdefault("empty_dates", []))
    empties.add(date_str)
    meta["empty_dates"] = sorted(list(empties))
    return cache


def _get_total_load(data: Dict[str, float]) -> float:
    """Calculate total_load from load + essential if not present (backward compatibility)."""
    if "total_load" in data:
        return float(data.get("total_load", 0.0))
    # Fallback: calculate from load + essential for old data
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
                from ..const import DEFAULT_TARIFF_VND_PER_KWH
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
                    import logging
                    _LOGGER = logging.getLogger(__name__)
                    _LOGGER.warning(f"Failed to delete {f}: {e}")
            # Keep directory for future use, don't rmdir
            return files_deleted > 0
    except Exception as e:
        import logging
        _LOGGER = logging.getLogger(__name__)
        _LOGGER.error(f"Failed to purge device cache: {e}")
    return False


