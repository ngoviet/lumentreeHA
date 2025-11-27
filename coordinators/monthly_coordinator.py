"""Monthly coordinator: ensure month aggregates via cache and on-demand fill."""

from __future__ import annotations

import datetime as dt
import asyncio
import logging
import calendar
from typing import Dict, Optional, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..services.aggregator import StatsAggregator
from ..services import cache as cache_io
from ..const import DEFAULT_TARIFF_VND_PER_KWH
from ..const import (
    DOMAIN,
    DEFAULT_MONTHLY_INTERVAL,
    KEY_MONTHLY_PV_KWH,
    KEY_MONTHLY_GRID_IN_KWH,
    KEY_MONTHLY_LOAD_KWH,
    KEY_MONTHLY_ESSENTIAL_KWH,
    KEY_MONTHLY_TOTAL_LOAD_KWH,
    KEY_MONTHLY_CHARGE_KWH,
    KEY_MONTHLY_DISCHARGE_KWH,
    KEY_MONTHLY_SAVED_KWH,
    KEY_MONTHLY_SAVINGS_VND,
    KEY_DAILY_PV_KWH,
    KEY_DAILY_GRID_IN_KWH,
    KEY_DAILY_LOAD_KWH,
    KEY_DAILY_ESSENTIAL_KWH,
    KEY_DAILY_CHARGE_KWH,
    KEY_DAILY_DISCHARGE_KWH,
)


_LOGGER = logging.getLogger(__name__)


class MonthlyStatsCoordinator(DataUpdateCoordinator[Dict[str, float]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str, entry_id: str | None = None) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        self._entry_id = entry_id
        self._last_month: tuple[int, int] | None = None  # (year, month)
        super().__init__(
            hass,
            _LOGGER,
            name="lumentree_monthly",
            update_interval=dt.timedelta(seconds=DEFAULT_MONTHLY_INTERVAL),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone()
            now = dt_util.now(timezone)
            year = now.year
            month = now.month
            
            # Check if month has changed - if so, finalize previous month's data
            if self._last_month is not None and self._last_month != (year, month):
                prev_year, prev_month = self._last_month
                await self._finalize_previous_month(prev_year, prev_month)

            # Load cache to build daily arrays
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, year
            )
            
            _LOGGER.info(f"Monthly coordinator: Using device_id: {self.aggregator._device_id}")
            _LOGGER.info(f"Monthly coordinator: Cache loaded for {year}: {len(cache.get('daily', {}))} days")
            _LOGGER.info(f"Monthly coordinator: Cache sample dates: {list(cache.get('daily', {}).keys())[:5]}")
            
            # Check if we have data for current month
            month_dates = [f"{year}-{month:02d}-{day:02d}" for day in range(1, 32)]
            month_data_count = sum(1 for date in month_dates if date in cache.get("daily", {}))
            _LOGGER.info(f"Monthly coordinator: Found {month_data_count} days with data for {year}-{month:02d}")

            # Build daily arrays for the current month (1-31)
            days_in_month = calendar.monthrange(year, month)[1]
            daily_pv = []
            daily_charge = []
            daily_discharge = []
            daily_grid = []
            daily_load = []
            daily_essential = []
            daily_total_load = []
            daily_saved_kwh = []
            daily_savings_vnd = []

            # Get today's data if we're in the current month
            today = now.date()
            today_str = today.strftime("%Y-%m-%d")
            today_day = today.day
            today_data_from_coord = None
            if today.year == year and today.month == month:
                today_data_from_coord = self._get_today_data_from_daily_coord()

            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{month:02d}-{day:02d}"
                
                # If this is today and we have real-time data, use it
                if day == today_day and today_data_from_coord:
                    daily_pv.append(float(today_data_from_coord.get("pv_today") or 0.0))
                    daily_charge.append(float(today_data_from_coord.get("charge_today") or 0.0))
                    daily_discharge.append(float(today_data_from_coord.get("discharge_today") or 0.0))
                    daily_grid.append(float(today_data_from_coord.get("grid_in_today") or 0.0))
                    load_val = float(today_data_from_coord.get("load_today") or 0.0)
                    essential_val = float(today_data_from_coord.get("essential_today") or 0.0)
                    daily_load.append(load_val)
                    daily_essential.append(essential_val)
                    daily_total_load.append(load_val + essential_val)
                    # Calculate savings for today
                    saved_kwh_today = max(0.0, (load_val + essential_val) - float(today_data_from_coord.get("grid_in_today") or 0.0))
                    from ..const import DEFAULT_TARIFF_VND_PER_KWH
                    daily_saved_kwh.append(saved_kwh_today)
                    daily_savings_vnd.append(saved_kwh_today * DEFAULT_TARIFF_VND_PER_KWH)
                else:
                    # Use cached data for past days
                    day_data = cache.get("daily", {}).get(date_str, {})
                    daily_pv.append(float(day_data.get("pv", 0.0)))
                    daily_charge.append(float(day_data.get("charge", 0.0)))
                    daily_discharge.append(float(day_data.get("discharge", 0.0)))
                    daily_grid.append(float(day_data.get("grid", 0.0)))
                    load_val = float(day_data.get("load", 0.0))
                    essential_val = float(day_data.get("essential", 0.0))
                    daily_load.append(load_val)
                    daily_essential.append(essential_val)
                    daily_total_load.append(float(day_data.get("total_load", load_val + essential_val)))
                    daily_saved_kwh.append(float(day_data.get("saved_kwh", 0.0)))
                    daily_savings_vnd.append(float(day_data.get("savings_vnd", 0.0)))

            _LOGGER.info(f"Monthly coordinator: Daily arrays built - PV first 5: {daily_pv[:5]}, Charge first 5: {daily_charge[:5]}")
            _LOGGER.info(f"Monthly coordinator: Daily arrays built - PV last 5: {daily_pv[-5:]}, Charge last 5: {daily_charge[-5:]}")

            # Summarize the month from cache (các ngày đã chốt)
            m = await self.aggregator.summarize_month(year, month)
            
            # Add today's data if we're in the current month (cộng dồn ngày hiện tại)
            today = now.date()
            if today.year == year and today.month == month:
                # Get today's data from daily coordinator (real-time data)
                today_data = self._get_today_data_from_daily_coord()
                if today_data:
                    m["pv"] = m.get("pv", 0.0) + float(today_data.get("pv_today") or 0.0)
                    m["grid"] = m.get("grid", 0.0) + float(today_data.get("grid_in_today") or 0.0)
                    load_val = float(today_data.get("load_today") or 0.0)
                    essential_val = float(today_data.get("essential_today") or 0.0)
                    m["load"] = m.get("load", 0.0) + load_val
                    m["essential"] = m.get("essential", 0.0) + essential_val
                    m["total_load"] = m.get("total_load", 0.0) + (load_val + essential_val)
                    m["charge"] = m.get("charge", 0.0) + float(today_data.get("charge_today") or 0.0)
                    m["discharge"] = m.get("discharge", 0.0) + float(today_data.get("discharge_today") or 0.0)
                    # Add today's savings
                    saved_kwh_today = float(today_data.get("saved_kwh") or max(0.0, (load_val + essential_val) - float(today_data.get("grid_in_today") or 0.0)))
                    m["saved_kwh"] = m.get("saved_kwh", 0.0) + saved_kwh_today
                    m["savings_vnd"] = m.get("savings_vnd", 0.0) + float(today_data.get("savings_vnd") or (saved_kwh_today * DEFAULT_TARIFF_VND_PER_KWH))
            
            _LOGGER.info(f"Monthly coordinator: Summary for {year}-{month:02d} (with today): PV={m.get('pv', 0.0)}, Charge={m.get('charge', 0.0)}")
            
            # Update last_month tracking
            self._last_month = (year, month)
            
            return {
                # Monthly totals (including today if current month)
                KEY_MONTHLY_PV_KWH: m.get("pv", 0.0),
                KEY_MONTHLY_GRID_IN_KWH: m.get("grid", 0.0),
                KEY_MONTHLY_LOAD_KWH: m.get("load", 0.0),
                KEY_MONTHLY_ESSENTIAL_KWH: m.get("essential", 0.0),
                KEY_MONTHLY_TOTAL_LOAD_KWH: m.get("total_load", 0.0),
                KEY_MONTHLY_CHARGE_KWH: m.get("charge", 0.0),
                KEY_MONTHLY_DISCHARGE_KWH: m.get("discharge", 0.0),
                KEY_MONTHLY_SAVED_KWH: m.get("saved_kwh", 0.0),
                KEY_MONTHLY_SAVINGS_VND: m.get("savings_vnd", 0.0),
                # Daily arrays for charting
                "daily_pv": daily_pv,
                "daily_charge": daily_charge,
                "daily_discharge": daily_discharge,
                "daily_grid": daily_grid,
                "daily_load": daily_load,
                "daily_essential": daily_essential,
                "daily_total_load": daily_total_load,
                "daily_saved_kwh": daily_saved_kwh,
                "daily_savings_vnd": daily_savings_vnd,
                "days_in_month": days_in_month,
                "year": year,
                "month": month,
            }
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout monthly") from err
        except Exception as err:
            _LOGGER.exception("Unexpected monthly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _finalize_previous_month(self, previous_year: int, previous_month: int) -> None:
        """Finalize previous month's data by ensuring cache is up-to-date."""
        try:
            _LOGGER.info(f"Month changed: Finalizing data for {previous_year}-{previous_month:02d}")
            # Load cache
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, previous_year
            )
            
            # Ensure monthly aggregates are recomputed for the previous month
            # This is already done by update_daily, but we recompute to be safe
            cache = cache_io.recompute_aggregates(cache)
            
            # Save finalized cache
            await self.hass.async_add_executor_job(
                cache_io.save_year, self.aggregator._device_id, previous_year, cache
            )
            
            _LOGGER.info(f"Finalized data for month {previous_year}-{previous_month:02d}")
        except Exception as err:
            _LOGGER.warning(f"Failed to finalize month {previous_year}-{previous_month:02d}: {err}")
            # Don't raise - this is a best-effort operation

    def _get_today_data_from_daily_coord(self) -> Dict[str, Any] | None:
        """Get today's real-time data from daily coordinator."""
        try:
            if not self._entry_id:
                return None
            
            domain_data = self.hass.data.get(DOMAIN, {})
            entry_data = domain_data.get(self._entry_id, {})
            daily_coord = entry_data.get("daily_coordinator")
            
            if daily_coord and daily_coord.data:
                return daily_coord.data
            return None
        except Exception:
            return None


