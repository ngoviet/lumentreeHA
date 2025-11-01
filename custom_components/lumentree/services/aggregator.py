"""Aggregator: fetch daily stats and build monthly/yearly with cache.

This module orchestrates backfill and delta updates using the HTTP API
client, and persists results via services.cache.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Dict, Any, Optional, Tuple

from homeassistant.core import HomeAssistant
from ..core.api_client import LumentreeHttpApiClient
from ..const import (
    BACKFILL_BASE_DELAY,
    BACKFILL_MAX_DELAY,
    EMPTY_DATA_THRESHOLD,
    MAX_DAYS_PER_YEAR,
)
from . import cache as cache_io


class StatsAggregator:
    def __init__(self, hass: HomeAssistant, api: LumentreeHttpApiClient, device_id: str) -> None:
        self._hass = hass
        self._api = api
        self._device_id = device_id

    async def fetch_day(self, date_str: str) -> Dict[str, float]:
        """Fetch a single day and return normalized totals in kWh.

        Returns keys: pv, grid, load, essential, charge, discharge
        Uses parallel API calls for 3x speed improvement.
        """
        # Build params once and call all 3 APIs in parallel
        params = {"deviceId": self._device_id, "queryDate": date_str}
        pv, bat, oth = await asyncio.gather(
            self._api._fetch_pv_data(params),
            self._api._fetch_battery_data(params),
            self._api._fetch_other_data(params),
            return_exceptions=True
        )

        # Handle exceptions gracefully
        if isinstance(pv, Exception):
            pv = {}
        if isinstance(bat, Exception):
            bat = {}
        if isinstance(oth, Exception):
            oth = {}

        return {
            "pv": float(pv.get("pv_today") or 0.0),
            "grid": float(oth.get("grid_in_today") or 0.0),
            "load": float(oth.get("load_today") or 0.0),
            "essential": float(oth.get("essential_today") or 0.0),
            "charge": float(bat.get("charge_today") or 0.0),
            "discharge": float(bat.get("discharge_today") or 0.0),
        }

    async def backfill_days(self, since: dt.date, until: dt.date) -> None:
        """Backfill inclusive date range with optimized batch cache I/O.

        Groups days by year and performs batch cache operations for better performance.
        Uses adaptive delay with exponential backoff on rate limits.
        """
        # Group days by year for batch processing
        days_by_year: Dict[int, list[dt.date]] = {}
        day = since
        while day <= until:
            year = day.year
            if year not in days_by_year:
                days_by_year[year] = []
            days_by_year[year].append(day)
            day += dt.timedelta(days=1)

        # Process each year's cache once
        delay = BACKFILL_BASE_DELAY
        for year, days in days_by_year.items():
            # Load cache once per year
            cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
            cache_dirty = False

            for day in days:
                date_str = day.strftime("%Y-%m-%d")
                
                # Skip if already exists or marked empty
                if date_str in cache.get("daily", {}) or date_str in set(cache.get("meta", {}).get("empty_dates", [])):
                    continue

                try:
                    vals = await self.fetch_day(date_str)
                    is_empty = all(
                        abs(vals.get(k, 0.0)) < EMPTY_DATA_THRESHOLD
                        for k in ("pv", "grid", "load", "essential", "charge", "discharge")
                    )
                    
                    if is_empty:
                        cache = cache_io.mark_empty(cache, date_str)
                    else:
                        cache, _m, _ = cache_io.update_daily(cache, date_str, vals)
                    
                    cache.setdefault("meta", {})["last_backfill_date"] = date_str
                    cache_dirty = True
                    
                    # Reset delay on success
                    delay = BACKFILL_BASE_DELAY
                    
                except Exception as err:
                    # Exponential backoff on errors (likely rate limit)
                    delay = min(delay * 2, BACKFILL_MAX_DELAY)
                    # Continue to next day
                    continue
                
                # Polite delay between API calls
                await asyncio.sleep(delay)

            # Save cache once per year if modified
            if cache_dirty:
                await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache)

    async def backfill_last_n_days(self, days: int) -> None:
        today = dt.date.today()
        start = today - dt.timedelta(days=days - 1)
        await self.backfill_days(start, today)

    async def summarize_month(self, year: int, month: int) -> Dict[str, float]:
        c = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
        return cache_io.summarize_month(c, month)

    async def summarize_year(self, year: int) -> Dict[str, float]:
        c = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
        return cache_io.summarize_year(c)

    async def backfill_all(self, max_years: int = 10, empty_streak: int = 14) -> None:
        """Backfill entire history backwards with optimized batch cache I/O.

        Stops when encountering `empty_streak` consecutive days without data
        or exceeding `max_years`.
        Uses optimized batch processing per year.
        """
        today = dt.date.today()
        limit_days = max_years * MAX_DAYS_PER_YEAR
        empty = 0
        delay = BACKFILL_BASE_DELAY
        
        # Track current year cache
        current_year = None
        cache = None

        for i in range(limit_days):
            day = today - dt.timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            year = day.year

            # Load cache when year changes
            if year != current_year:
                if cache is not None and current_year is not None:
                    # Save previous year's cache
                    await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, current_year, cache)
                cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
                current_year = year

            # Skip if already exists or marked empty
            if date_str in cache.get("daily", {}) or date_str in set(cache.get("meta", {}).get("empty_dates", [])):
                empty = 0
                continue

            try:
                vals = await self.fetch_day(date_str)
                is_empty = all(
                    abs(vals.get(k, 0.0)) < EMPTY_DATA_THRESHOLD
                    for k in ("pv", "grid", "load", "essential", "charge", "discharge")
                )
                
                if is_empty:
                    empty += 1
                    cache = cache_io.mark_empty(cache, date_str)
                    if empty >= empty_streak:
                        # Save before breaking
                        await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache)
                        break
                else:
                    empty = 0
                    cache, _m, _ = cache_io.update_daily(cache, date_str, vals)
                    cache.setdefault("meta", {})["last_backfill_date"] = date_str
                
                # Reset delay on success
                delay = BACKFILL_BASE_DELAY
                
            except Exception as err:
                # Exponential backoff on errors (likely rate limit)
                delay = min(delay * 2, BACKFILL_MAX_DELAY)
                continue

            await asyncio.sleep(delay)

        # Save final year's cache if needed
        if cache is not None and current_year is not None:
            await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, current_year, cache)

    async def backfill_gaps(self, max_years: int = 3, max_days_per_run: int = 60) -> int:
        """Fill missing days in cache by year with optimized batch I/O.

        Args:
            max_years: Number of recent years to check (backwards from current year)
            max_days_per_run: Limit of days to fetch in a single run

        Returns:
            Number of days filled.
        Uses optimized batch cache operations.
        """
        today = dt.date.today()
        filled = 0
        delay = BACKFILL_BASE_DELAY
        
        for year_offset in range(max_years):
            if filled >= max_days_per_run:
                break
                
            year = today.year - year_offset
            # Date range for the year
            start_date = dt.date(year, 1, 1)
            end_date = dt.date(year, 12, 31)
            if year == today.year:
                end_date = today

            # Load cache once per year
            cache_year = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
            cache_dirty = False

            day = start_date
            while day <= end_date:
                if filled >= max_days_per_run:
                    # Save before breaking
                    if cache_dirty:
                        await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache_year)
                    return filled
                    
                date_str = day.strftime("%Y-%m-%d")
                if date_str not in cache_year.get("daily", {}) and date_str not in set(cache_year.get("meta", {}).get("empty_dates", [])):
                    try:
                        vals = await self.fetch_day(date_str)
                        is_empty = all(
                            abs(vals.get(k, 0.0)) < EMPTY_DATA_THRESHOLD
                            for k in ("pv", "grid", "load", "essential", "charge", "discharge")
                        )
                        
                        if not is_empty:
                            cache_year, _m, _ = cache_io.update_daily(cache_year, date_str, vals)
                            cache_year.setdefault("meta", {})["last_backfill_date"] = date_str
                            cache_dirty = True
                            filled += 1
                            delay = BACKFILL_BASE_DELAY  # Reset on success
                        else:
                            cache_year = cache_io.mark_empty(cache_year, date_str)
                            cache_dirty = True
                            
                    except Exception as err:
                        # Exponential backoff on errors
                        delay = min(delay * 2, BACKFILL_MAX_DELAY)
                        continue
                    
                    await asyncio.sleep(delay)
                    
                day += dt.timedelta(days=1)

            # Save cache once per year if modified
            if cache_dirty:
                await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache_year)

        return filled


