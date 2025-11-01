"""Total coordinator: calculate lifetime totals from all cached data."""

from __future__ import annotations

import datetime as dt
import asyncio
import logging
import os
from typing import Dict, Optional, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..services.aggregator import StatsAggregator
from ..services import cache as cache_io
from ..const import (
    DEFAULT_YEARLY_INTERVAL,  # Use same interval as yearly
    MAX_YEARS_FOR_TOTAL,
    KEY_TOTAL_PV_KWH,
    KEY_TOTAL_GRID_IN_KWH,
    KEY_TOTAL_LOAD_KWH,
    KEY_TOTAL_ESSENTIAL_KWH,
    KEY_TOTAL_CHARGE_KWH,
    KEY_TOTAL_DISCHARGE_KWH,
)

_LOGGER = logging.getLogger(__name__)


class TotalStatsCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        super().__init__(
            hass,
            _LOGGER,
            name="lumentree_total",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(f"Total coordinator: Calculating lifetime totals for {self.device_sn}")
            
            # Calculate totals from all cached years
            total_pv = 0.0
            total_grid = 0.0
            total_load = 0.0
            total_essential = 0.0
            total_charge = 0.0
            total_discharge = 0.0
            
            # Get current year and scan backwards
            current_year = dt_util.now().year
            years_processed = 0
            earliest_year = None
            latest_year = None
            
            for year_offset in range(MAX_YEARS_FOR_TOTAL):
                year = current_year - year_offset
                cache = await self.hass.async_add_executor_job(
                    cache_io.load_year, self.aggregator._device_id, year
                )
                
                if not cache.get("daily"):  # No data for this year
                    continue
                
                years_processed += 1
                if earliest_year is None:
                    earliest_year = year
                latest_year = year
                
                # Sum from yearly_total if available, otherwise calculate from daily
                yearly_totals = cache.get("yearly_total", {})
                if yearly_totals:
                    total_pv += float(yearly_totals.get("pv", 0.0))
                    total_grid += float(yearly_totals.get("grid", 0.0))
                    total_load += float(yearly_totals.get("load", 0.0))
                    total_essential += float(yearly_totals.get("essential", 0.0))
                    total_charge += float(yearly_totals.get("charge", 0.0))
                    total_discharge += float(yearly_totals.get("discharge", 0.0))
                else:
                    # Fallback: sum from daily data
                    daily_data = cache.get("daily", {})
                    for date_str, day_data in daily_data.items():
                        total_pv += float(day_data.get("pv", 0.0))
                        total_grid += float(day_data.get("grid", 0.0))
                        total_load += float(day_data.get("load", 0.0))
                        total_essential += float(day_data.get("essential", 0.0))
                        total_charge += float(day_data.get("charge", 0.0))
                        total_discharge += float(day_data.get("discharge", 0.0))
                
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        f"Total coordinator: Year {year} - PV: {yearly_totals.get('pv', 0.0):.1f} kWh, "
                        f"Charge: {yearly_totals.get('charge', 0.0):.1f} kWh"
                    )
            
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    f"Total coordinator: Processed {years_processed} years ({earliest_year}-{latest_year}) - "
                    f"Lifetime totals - PV: {total_pv:.1f} kWh, Charge: {total_charge:.1f} kWh"
                )
            
            return {
                # Lifetime totals
                KEY_TOTAL_PV_KWH: round(total_pv, 3),
                KEY_TOTAL_GRID_IN_KWH: round(total_grid, 3),
                KEY_TOTAL_LOAD_KWH: round(total_load, 3),
                KEY_TOTAL_ESSENTIAL_KWH: round(total_essential, 3),
                KEY_TOTAL_CHARGE_KWH: round(total_charge, 3),
                KEY_TOTAL_DISCHARGE_KWH: round(total_discharge, 3),
                # Metadata
                "years_processed": years_processed,
                "earliest_year": earliest_year,
                "latest_year": latest_year,
                "last_updated": dt_util.now().isoformat(),
            }
            
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout total") from err
        except Exception as err:
            _LOGGER.exception("Unexpected total update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

