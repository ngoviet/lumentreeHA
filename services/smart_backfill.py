"""Smart backfill: fill the year caches a month at a time from getMonthData."""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
import time
from typing import Any

from ..const import today_in_ha
from ..core.api_client import LumentreeHttpApiClient
from . import cache as cache_io

_LOGGER = logging.getLogger(__name__)

# Metrics getMonthData reports, mapped to the cache's daily keys.
_MONTH_KEYS: dict[str, str] = {
    "pv": "pv",
    "grid": "grid",
    "homeload": "load",
    "essentialLoad": "essential",
    "bat": "charge",
    "batF": "discharge",
}
_DAY_METRICS = tuple(_MONTH_KEYS.values())

# A cached value this much below the API's counts as an unfinished day.  The
# API reports whole 0.1 kWh units, so anything smaller is rounding noise.
_PARTIAL_DAY_TOLERANCE = 0.05

_REQUEST_DELAY_SECONDS = 0.1


class _ParamsIgnoredError(Exception):
    """getMonthData answered a past month with another month's numbers."""


def _day_values(month_data: dict[str, Any], day: int) -> dict[str, float]:
    """One day's metrics (kWh) out of a getMonthData result."""
    values: dict[str, float] = {}
    for api_key, cache_key in _MONTH_KEYS.items():
        series = month_data.get(api_key) or []
        values[cache_key] = float(series[day - 1]) if day <= len(series) else 0.0
    return values


def _has_data(values: dict[str, Any]) -> bool:
    return any(float(values.get(key, 0.0) or 0.0) > 0.0 for key in _DAY_METRICS)


def _month_is_complete(cache: dict[str, Any], year: int, month: int, today: dt.date) -> bool:
    """True when every finished day of the month is cached or known empty."""
    daily = cache.get("daily", {})
    empty = set(cache.get("meta", {}).get("empty_dates", []))
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        date = dt.date(year, month, day)
        if date >= today:
            return False  # The month is not over, so the API has more to say.
        date_str = date.isoformat()
        if date_str not in daily and date_str not in empty:
            return False
    return True


def _month_has_cached_data(cache: dict[str, Any], year: int, month: int) -> bool:
    prefix = f"{year}-{month:02d}-"
    return any(
        date_str.startswith(prefix) and _has_data(values)
        for date_str, values in cache.get("daily", {}).items()
    )


def drop_unfinished_days(cache: dict[str, Any], today: dt.date) -> bool:
    """Remove entries for ``today`` and later; return True if any were removed.

    Earlier versions cached the partial reading of the day in progress and
    zero rows for the rest of the month.  An entry for a day that is not over
    blocks the day's real total from ever being written, and the in-progress
    row was counted a second time next to the live reading.
    """
    cutoff = today.isoformat()
    daily = cache.get("daily", {})
    stale = [date_str for date_str in daily if date_str >= cutoff]
    for date_str in stale:
        del daily[date_str]
    meta = cache.get("meta", {})
    empties = meta.get("empty_dates")
    if isinstance(empties, list):
        kept = [date_str for date_str in empties if date_str < cutoff]
        if len(kept) != len(empties):
            meta["empty_dates"] = kept
            stale.append("empty_dates")
    return bool(stale)


def merge_month(
    cache: dict[str, Any],
    year: int,
    month: int,
    month_data: dict[str, Any],
    today: dt.date,
) -> tuple[int, int, bool]:
    """Fold one getMonthData result into ``cache``.

    Only finished days (before ``today``) are written.  A day missing from the
    cache is added (or marked empty when the API has nothing for it either).
    A cached day is raised metric by metric to the API value where the cache
    is lower: a day's counters only grow, so a lower cached value is a reading
    taken before the day ended, or a discharge that an earlier version dropped.

    Returns:
        (days_added, days_updated, month_has_data)
    """
    days_added = 0
    days_updated = 0
    month_has_data = False
    daily = cache.setdefault("daily", {})
    empty = set(cache.get("meta", {}).get("empty_dates", []))

    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        date = dt.date(year, month, day)
        if date >= today:
            break
        date_str = date.isoformat()
        api_values = _day_values(month_data, day)
        api_has_data = _has_data(api_values)
        month_has_data = month_has_data or api_has_data

        existing = daily.get(date_str)
        if existing is None:
            if not api_has_data:
                if date_str not in empty:
                    cache_io.mark_empty(cache, date_str)
                    days_added += 1
                continue
            cache_io.update_daily(cache, date_str, api_values)
            days_added += 1
            continue

        merged = {key: float(existing.get(key, 0.0) or 0.0) for key in _DAY_METRICS}
        raised = False
        for key in _DAY_METRICS:
            if api_values[key] > merged[key] + _PARTIAL_DAY_TOLERANCE:
                merged[key] = api_values[key]
                raised = True
        if raised:
            cache_io.update_daily(cache, date_str, merged)
            days_updated += 1

    return days_added, days_updated, month_has_data


def _fingerprint(month_data: dict[str, Any]) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(month_data.get(key) or ()) for key in _MONTH_KEYS)


async def smart_backfill(
    hass, aggregator, max_years: int = 10, optimize_cache: bool = True
) -> dict[str, Any]:
    """Fill the year caches from getMonthData, newest month first.

    Each month is one request.  A month whose finished days are all cached
    (or known empty) is skipped without a request, so a restart on a warm
    cache asks for little more than the current month.  The walk stops at the
    first past year without a single day of data -- the device's history
    starts after it.

    This used to choose months from getYearData.  The captured responses in
    docs/ show that endpoint answering year=2026 with the twelve months of
    2025 (their sum is exactly getHistoryYearData's 2025 total, and Oct-Dec
    are non-zero on 2026-09-12), so the months it picked were last year's.

    Args:
        hass: HomeAssistant instance
        aggregator: StatsAggregator instance
        max_years: Maximum years to walk back, the current one included
        optimize_cache: If True, optimize cache after backfill

    Returns:
        Dictionary with backfill statistics
    """
    device_id = aggregator._device_id
    api_client: LumentreeHttpApiClient = aggregator._api
    today = today_in_ha(hass)

    start_time = time.time()
    stats: dict[str, Any] = {
        "years_processed": 0,
        "months_processed": 0,
        "days_added": 0,
        "days_updated": 0,
        "years_with_data": [],
        "errors": 0,
    }
    _LOGGER.info("Starting smart backfill for device %s (max_years=%s)", device_id, max_years)

    seen: dict[tuple[tuple[float, ...], ...], tuple[int, int]] = {}
    aborted = False

    for year in range(today.year, today.year - max(1, max_years), -1):
        cache = await hass.async_add_executor_job(cache_io.load_year, device_id, year, False)
        dirty = drop_unfinished_days(cache, today) if year == today.year else False
        year_has_data = False
        year_errors = 0
        last_month = today.month if year == today.year else 12

        for month in range(last_month, 0, -1):
            if _month_is_complete(cache, year, month, today):
                year_has_data = year_has_data or _month_has_cached_data(cache, year, month)
                continue
            try:
                month_data = await api_client.get_month_data(device_id, year, month)
            except Exception as err:
                _LOGGER.warning("getMonthData %s-%02d failed: %s", year, month, err)
                stats["errors"] += 1
                year_errors += 1
                continue

            fingerprint = _fingerprint(month_data)
            if any(any(series) for series in fingerprint):
                if fingerprint in seen:
                    # The vendor docs warn this endpoint may serve only the
                    # current month whatever is asked.  Writing that answer
                    # into another month would fabricate history.
                    other_year, other_month = seen[fingerprint]
                    _LOGGER.warning(
                        "getMonthData returned identical data for %s-%02d and %s-%02d; "
                        "the API appears to ignore the month. Stopping smart backfill -- "
                        "use the backfill_all service for history instead.",
                        year,
                        month,
                        other_year,
                        other_month,
                    )
                    aborted = True
                    break
                seen[fingerprint] = (year, month)

            added, updated, has_data = merge_month(cache, year, month, month_data, today)
            year_has_data = year_has_data or has_data
            if added or updated:
                dirty = True
                stats["days_added"] += added
                stats["days_updated"] += updated
                stats["months_processed"] += 1
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)

        if dirty:

            def _persist(c: dict[str, Any] = cache, y: int = year) -> None:
                cache_io.save_year(device_id, y, cache_io.recompute_aggregates(c))

            await hass.async_add_executor_job(_persist)
            stats["years_processed"] += 1
        if year_has_data:
            stats["years_with_data"].append(year)

        if aborted:
            break
        if year < today.year and not year_has_data and year_errors == 0:
            _LOGGER.info("No data at all in %s; history starts after it", year)
            break

    if optimize_cache and stats["years_with_data"]:
        try:
            from . import cache_optimizer

            for year in stats["years_with_data"]:
                result = await hass.async_add_executor_job(
                    cache_optimizer.optimize_year_cache, device_id, year, False
                )
                if result["status"] == "optimized":
                    _LOGGER.info(
                        "Optimized year %s: removed %s empty days, size reduction: %.1f%%",
                        year,
                        result["removed"],
                        result["size_reduction_percent"],
                    )
        except Exception as err:
            _LOGGER.warning("Error optimizing cache: %s", err)

    elapsed = time.time() - start_time
    stats["elapsed_seconds"] = round(elapsed, 2)
    _LOGGER.info(
        "Smart backfill completed: %s years written, %s months, %s days added, "
        "%s days updated, %s errors, took %.1fs",
        stats["years_processed"],
        stats["months_processed"],
        stats["days_added"],
        stats["days_updated"],
        stats["errors"],
        elapsed,
    )
    return stats
