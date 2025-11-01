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
from ..const import (
    DEFAULT_MONTHLY_INTERVAL,
    KEY_MONTHLY_PV_KWH,
    KEY_MONTHLY_GRID_IN_KWH,
    KEY_MONTHLY_LOAD_KWH,
    KEY_MONTHLY_ESSENTIAL_KWH,
    KEY_MONTHLY_CHARGE_KWH,
    KEY_MONTHLY_DISCHARGE_KWH,
)


_LOGGER = logging.getLogger(__name__)


class MonthlyStatsCoordinator(DataUpdateCoordinator[Dict[str, float]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
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

            for day in range(1, days_in_month + 1):
                date_str = f"{year}-{month:02d}-{day:02d}"
                day_data = cache.get("daily", {}).get(date_str, {})
                daily_pv.append(float(day_data.get("pv", 0.0)))
                daily_charge.append(float(day_data.get("charge", 0.0)))
                daily_discharge.append(float(day_data.get("discharge", 0.0)))
                daily_grid.append(float(day_data.get("grid", 0.0)))
                daily_load.append(float(day_data.get("load", 0.0)))
                daily_essential.append(float(day_data.get("essential", 0.0)))

            _LOGGER.info(f"Monthly coordinator: Daily arrays built - PV first 5: {daily_pv[:5]}, Charge first 5: {daily_charge[:5]}")
            _LOGGER.info(f"Monthly coordinator: Daily arrays built - PV last 5: {daily_pv[-5:]}, Charge last 5: {daily_charge[-5:]}")

            # Summarize the month and map to integration keys
            m = await self.aggregator.summarize_month(year, month)
            _LOGGER.info(f"Monthly coordinator: Summary for {year}-{month:02d}: PV={m.get('pv', 0.0)}, Charge={m.get('charge', 0.0)}")
            
            return {
                # Monthly totals
                KEY_MONTHLY_PV_KWH: m.get("pv", 0.0),
                KEY_MONTHLY_GRID_IN_KWH: m.get("grid", 0.0),
                KEY_MONTHLY_LOAD_KWH: m.get("load", 0.0),
                KEY_MONTHLY_ESSENTIAL_KWH: m.get("essential", 0.0),
                KEY_MONTHLY_CHARGE_KWH: m.get("charge", 0.0),
                KEY_MONTHLY_DISCHARGE_KWH: m.get("discharge", 0.0),
                # Daily arrays for charting
                "daily_pv": daily_pv,
                "daily_charge": daily_charge,
                "daily_discharge": daily_discharge,
                "daily_grid": daily_grid,
                "daily_load": daily_load,
                "daily_essential": daily_essential,
                "days_in_month": days_in_month,
                "year": year,
                "month": month,
            }
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout monthly") from err
        except Exception as err:
            _LOGGER.exception("Unexpected monthly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err


