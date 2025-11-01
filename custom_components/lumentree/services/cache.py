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
from typing import Dict, Any, Tuple

from ..const import MONTHS_PER_YEAR


CACHE_BASE_DIR = os.path.join(".storage", "lumentree_stats")


_LOGGER = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    """Ensure directory exists, creating if necessary."""
    try:
        os.makedirs(path, exist_ok=True)
    except (OSError, PermissionError) as err:
        # Log only if it's not just a permission issue we can ignore
        _LOGGER.warning(f"Could not create directory {path}: {err}")


def _empty_month() -> list[float]:
    """Return an empty monthly array (12 zeros)."""
    return [0.0 for _ in range(MONTHS_PER_YEAR)]


def _empty_cache() -> Dict[str, Any]:
    return {
        "daily": {},
        "monthly": {
            "pv": _empty_month(),
            "grid": _empty_month(),
            "load": _empty_month(),
            "essential": _empty_month(),
            "charge": _empty_month(),
            "discharge": _empty_month(),
        },
        "yearly_total": {"pv": 0.0, "grid": 0.0, "load": 0.0, "essential": 0.0, "charge": 0.0, "discharge": 0.0},
        "meta": {
            "version": 1,
            "last_backfill_date": None,
            # Data coverage range (earliest/latest dates with data)
            "coverage": {"earliest": None, "latest": None},
            # Dates confirmed as empty (to skip permanently)
            "empty_dates": [],
        },
    }


def cache_path(device_id: str, year: int) -> str:
    dev_dir = os.path.join(CACHE_BASE_DIR, device_id)
    _ensure_dir(dev_dir)
    return os.path.join(dev_dir, f"{year}.json")


def load_year(device_id: str, year: int) -> Dict[str, Any]:
    """Load cache for a specific year, returning empty cache if not found or invalid."""
    path = cache_path(device_id, year)
    if not os.path.exists(path):
        return _empty_cache()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else _empty_cache()
    except (json.JSONDecodeError, OSError, IOError) as err:
        _LOGGER.warning(f"Failed to load cache for {device_id}/{year}: {err}")
        return _empty_cache()


def save_year(device_id: str, year: int, data: Dict[str, Any]) -> None:
    """Save cache for a specific year."""
    path = cache_path(device_id, year)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, IOError, PermissionError) as err:
        _LOGGER.warning(f"Failed to save cache for {device_id}/{year}: {err}")


def update_daily(
    cache: Dict[str, Any], date_str: str, values: Dict[str, float]
) -> Tuple[Dict[str, Any], int, int]:
    """Update one day in cache and recompute its month index.

    Returns (cache, month_index, year_changed_flag)
    """
    # Store daily
    cache.setdefault("daily", {})[date_str] = {
        "pv": float(values.get("pv", 0.0)),
        "grid": float(values.get("grid", 0.0)),
        "load": float(values.get("load", 0.0)),
        "essential": float(values.get("essential", 0.0)),
        "charge": float(values.get("charge", 0.0)),
        "discharge": float(values.get("discharge", 0.0)),
    }

    # Update coverage and remove date from empty_dates if present
    meta = cache.setdefault("meta", {})
    cov = meta.setdefault("coverage", {"earliest": None, "latest": None})
    try:
        if cov["earliest"] is None or date_str < cov["earliest"]:
            cov["earliest"] = date_str
        if cov["latest"] is None or date_str > cov["latest"]:
            cov["latest"] = date_str
    except (KeyError, TypeError):
        # Coverage structure might be invalid, ignore
        pass
    try:
        empties = set(meta.setdefault("empty_dates", []))
        if date_str in empties:
            empties.discard(date_str)
            meta["empty_dates"] = sorted(list(empties))
    except (KeyError, TypeError):
        # Empty dates structure might be invalid, ignore
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
    for key in ("pv", "grid", "load", "essential", "charge", "discharge"):
        if key not in monthly:
            monthly[key] = _empty_month()
        # sum all days of the month
        s = 0.0
        for d, v in cache["daily"].items():
            try:
                if int(d[5:7]) == month:
                    s += float(v.get(key, 0.0))
            except Exception:
                continue
        monthly[key][m_idx] = round(s, 6)

    # Recompute yearly totals
    ytot = cache.setdefault("yearly_total", {})
    for key in ("pv", "grid", "load", "essential", "charge", "discharge"):
        ytot[key] = round(sum(monthly.get(key, _empty_month())), 6)

    return cache, m_idx, 1


def mark_empty(cache: Dict[str, Any], date_str: str) -> Dict[str, Any]:
    """Mark a date as empty to skip during backfill/gap-fill.

    Does not store daily data for empty dates, only records in meta.empty_dates.
    """
    meta = cache.setdefault("meta", {})
    empties = set(meta.setdefault("empty_dates", []))
    empties.add(date_str)
    meta["empty_dates"] = sorted(list(empties))
    return cache


def summarize_month(cache: Dict[str, Any], month: int) -> Dict[str, float]:
    idx = month - 1
    m = cache.get("monthly", {})
    return {
        "pv": float(m.get("pv", _empty_month())[idx]),
        "grid": float(m.get("grid", _empty_month())[idx]),
        "load": float(m.get("load", _empty_month())[idx]),
        "essential": float(m.get("essential", _empty_month())[idx]),
        "charge": float(m.get("charge", _empty_month())[idx]),
        "discharge": float(m.get("discharge", _empty_month())[idx]),
    }


def summarize_year(cache: Dict[str, Any]) -> Dict[str, float]:
    return {k: float(v) for k, v in cache.get("yearly_total", {}).items()}


def recompute_aggregates(cache: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild monthly arrays and yearly totals from daily map."""
    monthly = {
        "pv": _empty_month(),
        "grid": _empty_month(),
        "load": _empty_month(),
        "essential": _empty_month(),
        "charge": _empty_month(),
        "discharge": _empty_month(),
    }
    for d, v in cache.get("daily", {}).items():
        try:
            month = int(d[5:7]) - 1
        except Exception:
            continue
        for key in monthly.keys():
            monthly[key][month] += float(v.get(key, 0.0))
    cache["monthly"] = {k: [round(x, 6) for x in vals] for k, vals in monthly.items()}

    ytot = {k: round(sum(vals), 6) for k, vals in cache["monthly"].items()}
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
    dev_dir = os.path.join(CACHE_BASE_DIR, device_id)
    try:
        if os.path.isdir(dev_dir):
            for f in os.listdir(dev_dir):
                try:
                    os.remove(os.path.join(dev_dir, f))
                except Exception:
                    pass
            os.rmdir(dev_dir)
            return True
    except Exception:
        pass
    return False


