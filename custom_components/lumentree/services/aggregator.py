"""Aggregator: fetch daily stats and build monthly/yearly with cache.

This module orchestrates backfill and delta updates using the HTTP API
client, and persists results via services.cache.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Dict, Any, Optional, Tuple

from homeassistant.core import HomeAssistant
from ..core.api_client import LumentreeHttpApiClient
from . import cache as cache_io

_LOGGER = logging.getLogger(__name__)


class StatsAggregator:
    def __init__(self, hass: HomeAssistant, api: LumentreeHttpApiClient, device_id: str) -> None:
        self._hass = hass
        self._api = api
        self._device_id = device_id

    async def get_year_data_from_api(self, year: int) -> Dict[str, Any]:
        """Get yearly data from API using getYearData endpoint.
        
        This provides pre-aggregated monthly data that may not be available
        through daily API calls.
        
        Args:
            year: Year to fetch
            
        Returns:
            Dictionary with monthly arrays (12 values each) for:
            - pv, grid, homeload, essentialLoad, bat
            Values are in kWh (already converted from 0.1 kWh)
        """
        try:
            year_data = await self._api.get_year_data(self._device_id, year)
            
            # Map API keys to our internal keys
            # API returns: pv, grid, homeload, essentialLoad, bat, batF
            # We need: pv, grid, load, essential, charge, discharge
            result = {
                "pv": year_data.get("pv", [0.0] * 12),
                "grid": year_data.get("grid", [0.0] * 12),
                "load": year_data.get("homeload", [0.0] * 12),  # Map homeload -> load
                "essential": year_data.get("essentialLoad", [0.0] * 12),  # Map essentialLoad -> essential
                "charge": year_data.get("bat", [0.0] * 12),  # bat = charge
                "discharge": year_data.get("batF", [0.0] * 12),  # batF = discharge
            }
            
            return result
        except Exception as err:
            _LOGGER.error(f"Error getting year data from API for {year}: {err}")
            return {
                "pv": [0.0] * 12,
                "grid": [0.0] * 12,
                "load": [0.0] * 12,
                "essential": [0.0] * 12,
                "charge": [0.0] * 12,
                "discharge": [0.0] * 12,
            }

    async def smart_backfill(self, max_years: int = 10, optimize_cache: bool = True) -> Dict[str, Any]:
        """Smart backfill using getYearData/getMonthData APIs for optimal performance.
        
        This is much faster than traditional daily backfill because:
        - Uses getYearData to quickly identify years/months with data
        - Uses getMonthData to backfill entire months at once
        - Skips days that already have data
        - Auto-optimizes cache after backfill
        
        Args:
            max_years: Maximum years to backfill
            optimize_cache: If True, optimize cache after backfill
            
        Returns:
            Dictionary with backfill statistics
        """
        from .smart_backfill import smart_backfill
        return await smart_backfill(self._hass, self, max_years, optimize_cache)

    async def get_earliest_data_date(self) -> Dict[str, Any] | None:
        """Get earliest date when device has data.
        
        Returns:
            Dictionary with earliest data info or None:
            {
                "date": "YYYY-MM-DD",
                "year": int,
                "month": int,
                "source": "cache" or "api",
                "method": "daily" or "monthly"
            }
        """
        from .data_detection import find_earliest_data_date
        
        try:
            result = await find_earliest_data_date(
                self._hass,
                self,
                prefer_api=True
            )
            return result
        except Exception as err:
            _LOGGER.error(f"Error finding earliest data date: {err}")
            return None

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

        # Track API failures for logging
        api_failures = []
        
        # Handle exceptions gracefully
        if isinstance(pv, Exception):
            api_failures.append(f"PV: {type(pv).__name__}")
            pv = {}
        if isinstance(bat, Exception):
            api_failures.append(f"Battery: {type(bat).__name__}")
            bat = {}
        if isinstance(oth, Exception):
            api_failures.append(f"Other: {type(oth).__name__}")
            oth = {}

        # Extract values with fallback to series sums if tableValue is None
        # PV: prefer tableValue, fallback to pv_sum_kwh from series
        pv_value = pv.get("pv_today")
        if pv_value is None and "pv_sum_kwh" in pv:
            pv_value = pv.get("pv_sum_kwh")
        pv_final = float(pv_value or 0.0)
        
        # Grid
        grid_value = oth.get("grid_in_today")
        if grid_value is None and "grid_series_5min_kwh" in oth:
            grid_series = oth.get("grid_series_5min_kwh", [])
            if grid_series:
                grid_value = sum(grid_series)
        grid_final = float(grid_value or 0.0)
        
        # Load and Essential
        load_value = oth.get("load_today")
        if load_value is None and "load_series_5min_kwh" in oth:
            load_series = oth.get("load_series_5min_kwh", [])
            if load_series:
                load_value = sum(load_series)
        load_final = float(load_value or 0.0)
        
        essential_value = oth.get("essential_today")
        if essential_value is None and "essential_series_5min_kwh" in oth:
            essential_series = oth.get("essential_series_5min_kwh", [])
            if essential_series:
                essential_value = sum(essential_series)
        essential_final = float(essential_value or 0.0)
        
        total_load_value = load_final + essential_final
        
        # Battery charge/discharge
        charge_value = float(bat.get("charge_today") or 0.0)
        discharge_value = float(bat.get("discharge_today") or 0.0)
        
        # Log API failures if any
        if api_failures:
            _LOGGER.warning(
                f"API failures for {date_str}: {', '.join(api_failures)}. "
                f"Values: pv={pv_final:.2f}, grid={grid_final:.2f}, load={load_final:.2f}, "
                f"essential={essential_final:.2f}, charge={charge_value:.2f}, discharge={discharge_value:.2f}"
            )
        
        return {
            "pv": pv_final,
            "grid": grid_final,
            "load": load_final,
            "essential": essential_final,
            "total_load": total_load_value,
            "charge": charge_value,
            "discharge": discharge_value,
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
        base_delay = 0.2
        delay = base_delay
        for year, days in days_by_year.items():
            # Load cache once per year
            cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
            cache_dirty = False

            for day in days:
                date_str = day.strftime("%Y-%m-%d")
                
                # Skip if already exists in daily cache
                # Since server always returns same structure (0s when no data),
                # we store ALL days in daily cache
                if date_str in cache.get("daily", {}):
                    continue

                try:
                    vals = await self.fetch_day(date_str)
                    # Store all days in cache, even if all values are 0
                    # This matches server behavior (always returns same structure)
                    cache, _m, _ = cache_io.update_daily(cache, date_str, vals)
                    cache.setdefault("meta", {})["last_backfill_date"] = date_str
                    cache_dirty = True
                    
                    # Reset delay on success
                    delay = base_delay
                    
                except Exception as err:
                    # Exponential backoff on errors (likely rate limit)
                    delay = min(delay * 2, 5.0)  # Cap at 5 seconds
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

    async def backfill_all(self, max_years: int | None = 5, empty_streak: int = 14) -> None:
        """Backfill toàn bộ lịch sử lùi theo ngày với batch cache I/O.

        - Nếu `max_years` được chỉ định: quét đủ số năm đó, KHÔNG dừng vì empty_streak
          (hữu ích khi có khoảng thời gian dài thiết bị nghỉ không có dữ liệu)
        - Nếu `max_years=None`: quét không giới hạn, dừng khi gặp `empty_streak` ngày rỗng liên tiếp
        
        Args:
            max_years: Tối đa số năm cần quét (mặc định 5). None = không giới hạn, chỉ dừng theo empty_streak
            empty_streak: Số ngày liên tiếp không có dữ liệu để dừng (chỉ áp dụng khi max_years=None)
        
        Uses optimized batch processing per year.
        """
        start_time = time.time()
        today = dt.date.today()
        empty = 0
        base_delay = 0.1  # Reduced from 0.2s for better performance
        delay = base_delay
        
        # Statistics tracking
        total_fetched = 0
        total_empty = 0
        total_skipped = 0
        total_errors = 0
        days_in_current_year = 0
        stop_reason = None
        
        # Track current year cache
        current_year = None
        cache = None
        last_progress_log = 0

        # Calculate limit_days: None means unlimited (only stop by empty_streak)
        # If max_years is specified, ignore empty_streak and always complete the years
        ignore_empty_streak = max_years is not None
        
        if max_years is None:
            # Unlimited - use a very large number but rely on empty_streak to stop
            limit_days = 365 * 100  # 100 years as safety limit, but should stop earlier
            limit_info = "unlimited (stops at empty_streak)"
        else:
            limit_days = max_years * 366
            limit_info = f"{max_years} years ({limit_days} days, ignoring empty_streak)"

        _LOGGER.info(
            f"Backfill started: device_id={self._device_id}, max_years={max_years}, "
            f"limit={limit_info}, empty_streak={empty_streak if not ignore_empty_streak else 'ignored'}, delay={base_delay}s"
        )

        for i in range(limit_days):
            day = today - dt.timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            year = day.year

            # Load cache when year changes
            if year != current_year:
                if cache is not None and current_year is not None:
                    # Save previous year's cache
                    await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, current_year, cache)
                    _LOGGER.info(
                        f"Year {current_year} completed: fetched {days_in_current_year} days. "
                        f"Total progress: {total_fetched} fetched, {total_empty} empty, {total_skipped} skipped"
                    )
                
                cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
                current_year = year
                days_in_current_year = 0
                _LOGGER.info(f"Processing year {year}...")

            # Skip if already exists in daily data
            # Since server always returns same structure (0s when no data),
            # we store ALL days in daily cache, so we only skip if already cached
            if date_str in cache.get("daily", {}):
                empty = 0
                total_skipped += 1
                continue

            # Progress logging every 50 days
            if total_fetched > 0 and total_fetched % 50 == 0 and total_fetched != last_progress_log:
                elapsed = time.time() - start_time
                _LOGGER.info(
                    f"Progress: {total_fetched} days fetched, {total_empty} empty, "
                    f"currently at {date_str} (elapsed: {elapsed:.1f}s)"
                )
                last_progress_log = total_fetched

            try:
                vals = await self.fetch_day(date_str)
                
                # Since server always returns same structure (0s when no data),
                # we store ALL days in daily cache, even if all values are 0.
                # This simplifies logic and allows easy re-checking later.
                empty = 0  # Reset empty streak when we have a response (even if all zeros)
                cache, _m, _ = cache_io.update_daily(cache, date_str, vals)
                cache.setdefault("meta", {})["last_backfill_date"] = date_str
                total_fetched += 1
                days_in_current_year += 1
                
                # Check if day has meaningful data (for statistics only)
                has_data = any(abs(vals.get(k, 0.0)) > 0.001 for k in ("pv", "grid", "load", "essential", "charge", "discharge"))
                if not has_data:
                    total_empty += 1
                    
                # For empty_streak stopping (only in unlimited mode), track consecutive empty days
                if not ignore_empty_streak:
                    if not has_data:
                        empty += 1
                        # Log empty streak progress
                        if empty % 5 == 0:
                            _LOGGER.info(f"Empty streak: {empty}/{empty_streak} consecutive empty days at {date_str}")
                        
                        if empty >= empty_streak:
                            stop_reason = f"empty_streak ({empty} consecutive empty days)"
                            _LOGGER.info(
                                f"Backfill stopping: reached {empty_streak} consecutive empty days at {date_str}. "
                                f"This indicates we've reached the beginning of inverter usage history. "
                                f"Total fetched: {total_fetched} days, empty: {total_empty} days"
                            )
                            # Save before breaking
                            await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache)
                            break
                    else:
                        empty = 0
                
                # Reset delay on success
                if delay > base_delay:
                    _LOGGER.info(f"Resetting delay to {base_delay}s after successful fetch")
                delay = base_delay
                
            except Exception as err:
                total_errors += 1
                # Exponential backoff on errors (likely rate limit)
                old_delay = delay
                delay = min(delay * 2, 5.0)  # Cap at 5 seconds
                if delay > old_delay:
                    _LOGGER.warning(
                        f"Error fetching {date_str}: {err}. Increasing delay to {delay}s "
                        f"(total errors: {total_errors})"
                    )
                else:
                    _LOGGER.error(f"Error fetching {date_str}: {err}")
                continue

            await asyncio.sleep(delay)

        # Check if we hit the limit
        if stop_reason is None:
            stop_reason = f"limit_days reached ({limit_days} days)"

        # Save final year's cache if needed
        if cache is not None and current_year is not None:
            if days_in_current_year > 0:
                _LOGGER.info(
                    f"Year {current_year} completed: fetched {days_in_current_year} days. "
                    f"Total progress: {total_fetched} fetched, {total_empty} empty, {total_skipped} skipped"
                )
            await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, current_year, cache)

        # Final summary
        elapsed_time = time.time() - start_time
        _LOGGER.info(
            f"Backfill completed: device_id={self._device_id}, reason={stop_reason}, "
            f"fetched={total_fetched} days, empty={total_empty} days, "
            f"skipped={total_skipped} days, errors={total_errors}, "
            f"elapsed={elapsed_time:.1f}s ({elapsed_time/60:.1f} minutes)"
        )

    async def backfill_gaps(self, max_years: int = 3, max_days_per_run: int = 60) -> int:
        """Lấp các ngày còn thiếu trong cache theo từng năm với batch I/O.

        - max_years: số năm gần nhất để kiểm tra (tính từ năm hiện tại lùi lại)
        - max_days_per_run: giới hạn số ngày được fetch trong một lần chạy

        Trả về số ngày đã lấp.
        Uses optimized batch cache operations.
        """
        today = dt.date.today()
        filled = 0
        base_delay = 0.2
        delay = base_delay
        
        for year_offset in range(max_years):
            if filled >= max_days_per_run:
                break
                
            year = today.year - year_offset
            # Phạm vi ngày của năm
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
                # Skip if already exists in daily cache
                # Since server always returns same structure, we store ALL days (even with 0s)
                if date_str not in cache_year.get("daily", {}):
                    try:
                        vals = await self.fetch_day(date_str)
                        # Store all days in cache, even if all values are 0
                        cache_year, _m, _ = cache_io.update_daily(cache_year, date_str, vals)
                        cache_year.setdefault("meta", {})["last_backfill_date"] = date_str
                        cache_dirty = True
                        filled += 1
                        delay = base_delay  # Reset on success
                            
                    except Exception as err:
                        # Exponential backoff on errors
                        delay = min(delay * 2, 5.0)  # Cap at 5 seconds
                        continue
                    
                    await asyncio.sleep(delay)
                    
                day += dt.timedelta(days=1)

            # Save cache once per year if modified
            if cache_dirty:
                await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache_year)

        return filled

    async def backfill_empty_dates(self, max_years: int = 5, max_days_per_run: int = 100) -> Dict[str, int]:
        """Backfill lại các ngày đã bị đánh dấu empty để kiểm tra lại với logic mới.
        
        Hữu ích sau khi cải thiện logic fetch/parse để phát hiện các ngày bị đánh dấu
        empty nhầm do API failures hoặc logic cũ.
        
        Args:
            max_years: Số năm gần nhất để kiểm tra (tính từ năm hiện tại lùi lại)
            max_days_per_run: Giới hạn số ngày được fetch trong một lần chạy
            
        Returns:
            Dictionary với statistics: {"recovered": N, "confirmed_empty": M, "errors": K}
        """
        start_time = time.time()
        today = dt.date.today()
        base_delay = 0.1
        delay = base_delay
        
        recovered = 0
        confirmed_empty = 0
        total_errors = 0
        
        _LOGGER.info(
            f"Starting backfill_empty_dates: device_id={self._device_id}, "
            f"max_years={max_years}, max_days_per_run={max_days_per_run}"
        )
        
        # Collect all empty dates from specified years
        empty_dates_by_year: Dict[int, list[str]] = {}
        for year_offset in range(max_years):
            year = today.year - year_offset
            cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
            empty_dates = cache.get("meta", {}).get("empty_dates", [])
            if empty_dates:
                empty_dates_by_year[year] = sorted(empty_dates)
                _LOGGER.info(f"Found {len(empty_dates)} empty dates in year {year}")
        
        total_empty = sum(len(dates) for dates in empty_dates_by_year.values())
        _LOGGER.info(f"Total empty dates to re-check: {total_empty}")
        
        if total_empty == 0:
            _LOGGER.info("No empty dates to re-check")
            return {"recovered": 0, "confirmed_empty": 0, "errors": 0}
        
        # Process each year
        for year, empty_dates in empty_dates_by_year.items():
            if recovered + confirmed_empty >= max_days_per_run:
                _LOGGER.info(f"Reached max_days_per_run limit ({max_days_per_run}), stopping")
                break
            
            cache = await self._hass.async_add_executor_job(cache_io.load_year, self._device_id, year)
            cache_dirty = False
            
            for date_str in empty_dates:
                if recovered + confirmed_empty >= max_days_per_run:
                    break
                
                try:
                    _LOGGER.debug(f"Re-checking empty date: {date_str}")
                    vals = await self.fetch_day(date_str)
                    
                    # Check with improved logic
                    has_data = any(abs(vals.get(k, 0.0)) > 0.001 for k in ("pv", "grid", "load", "essential", "charge", "discharge"))
                    
                    if has_data:
                        # Has data - recover it!
                        # Check if it was in empty_dates before
                        was_empty = date_str in cache.get("meta", {}).get("empty_dates", [])
                        cache, _m, _ = cache_io.update_daily(cache, date_str, vals)
                        cache.setdefault("meta", {})["last_backfill_date"] = date_str
                        cache_dirty = True
                        recovered += 1
                        
                        # Verify it was removed from empty_dates
                        still_empty = date_str in cache.get("meta", {}).get("empty_dates", [])
                        if was_empty and still_empty:
                            _LOGGER.warning(f"WARNING: {date_str} still in empty_dates after recovery!")
                        elif was_empty:
                            _LOGGER.info(f"Successfully removed {date_str} from empty_dates")
                        
                        _LOGGER.info(
                            f"Recovered {date_str}: pv={vals.get('pv', 0.0):.2f}, "
                            f"grid={vals.get('grid', 0.0):.2f}, load={vals.get('load', 0.0):.2f}, "
                            f"essential={vals.get('essential', 0.0):.2f}, "
                            f"charge={vals.get('charge', 0.0):.2f}, discharge={vals.get('discharge', 0.0):.2f}"
                        )
                        delay = base_delay  # Reset on success
                    else:
                        # Still empty - confirm it
                        confirmed_empty += 1
                        _LOGGER.debug(
                            f"Confirmed empty {date_str}: all values < 0.001 kWh. "
                            f"Values: pv={vals.get('pv', 0.0):.4f}, grid={vals.get('grid', 0.0):.4f}, "
                            f"load={vals.get('load', 0.0):.4f}, essential={vals.get('essential', 0.0):.4f}, "
                            f"charge={vals.get('charge', 0.0):.4f}, discharge={vals.get('discharge', 0.0):.4f}"
                        )
                        delay = base_delay
                    
                except Exception as err:
                    total_errors += 1
                    old_delay = delay
                    delay = min(delay * 2, 5.0)
                    if delay > old_delay:
                        _LOGGER.warning(
                            f"Error re-checking {date_str}: {err}. Increasing delay to {delay}s "
                            f"(total errors: {total_errors})"
                        )
                    else:
                        _LOGGER.error(f"Error re-checking {date_str}: {err}")
                    continue
                
                await asyncio.sleep(delay)
            
            # Save cache if modified
            if cache_dirty:
                await self._hass.async_add_executor_job(cache_io.save_year, self._device_id, year, cache)
                remaining_empty = len(cache.get("meta", {}).get("empty_dates", []))
                _LOGGER.info(
                    f"Saved cache for year {year}: recovered {recovered} days so far. "
                    f"Remaining empty dates in {year}: {remaining_empty}"
                )
        
        # Final summary
        elapsed_time = time.time() - start_time
        result = {
            "recovered": recovered,
            "confirmed_empty": confirmed_empty,
            "errors": total_errors
        }
        _LOGGER.info(
            f"backfill_empty_dates completed: device_id={self._device_id}, "
            f"recovered={recovered} days, confirmed_empty={confirmed_empty} days, "
            f"errors={total_errors}, elapsed={elapsed_time:.1f}s ({elapsed_time/60:.1f} minutes)"
        )
        return result


