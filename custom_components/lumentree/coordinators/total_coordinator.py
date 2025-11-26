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
    DOMAIN,
    DEFAULT_YEARLY_INTERVAL,  # Use same interval as yearly
    KEY_TOTAL_PV_KWH,
    KEY_TOTAL_GRID_IN_KWH,
    KEY_TOTAL_LOAD_KWH,
    KEY_TOTAL_ESSENTIAL_KWH,
    KEY_TOTAL_TOTAL_LOAD_KWH,
    KEY_TOTAL_CHARGE_KWH,
    KEY_TOTAL_DISCHARGE_KWH,
    KEY_TOTAL_SAVED_KWH,
    KEY_TOTAL_SAVINGS_VND,
)

_LOGGER = logging.getLogger(__name__)


class TotalStatsCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str, entry_id: str | None = None) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        self._entry_id = entry_id
        super().__init__(
            hass,
            _LOGGER,
            name="lumentree_total",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            _LOGGER.info(f"Total coordinator: Calculating lifetime totals for {self.device_sn}")
            
            # Calculate totals from all cached years
            total_pv = 0.0
            total_grid = 0.0
            total_load = 0.0
            total_essential = 0.0
            total_total_load = 0.0
            total_charge = 0.0
            total_discharge = 0.0
            total_saved_kwh = 0.0
            total_savings_vnd = 0.0
            
            # Determine which cached years exist (include current year for live data)
            current_year = dt_util.now().year
            cached_years = await self.hass.async_add_executor_job(
                cache_io.list_cached_years, self.aggregator._device_id
            )
            years_to_process = sorted(set(cached_years + [current_year]), reverse=True)
            years_processed = 0
            earliest_year = None
            latest_year = None
            
            for year in years_to_process:
                cache = await self.hass.async_add_executor_job(
                    cache_io.load_year, self.aggregator._device_id, year
                )
                
                if not cache.get("daily"):  # No data for this year
                    continue
                
                years_processed += 1
                if earliest_year is None or year < earliest_year:
                    earliest_year = year
                if latest_year is None or year > latest_year:
                    latest_year = year
                
                # Sum from yearly_total if available, otherwise calculate from daily
                yearly_totals = cache.get("yearly_total", {})
                if yearly_totals:
                    total_pv += float(yearly_totals.get("pv", 0.0))
                    total_grid += float(yearly_totals.get("grid", 0.0))
                    load_val = float(yearly_totals.get("load", 0.0))
                    essential_val = float(yearly_totals.get("essential", 0.0))
                    total_load += load_val
                    total_essential += essential_val
                    # Backward compatibility: calculate total_load if missing in old data
                    cached_total_load = yearly_totals.get("total_load")
                    if cached_total_load is not None:
                        total_total_load += float(cached_total_load)
                    else:
                        # Old data: calculate from load + essential
                        total_total_load += load_val + essential_val
                    total_charge += float(yearly_totals.get("charge", 0.0))
                    total_discharge += float(yearly_totals.get("discharge", 0.0))
                    total_saved_kwh += float(yearly_totals.get("saved_kwh", 0.0))
                    total_savings_vnd += float(yearly_totals.get("savings_vnd", 0.0))
                else:
                    # Fallback: sum from daily data
                    daily_data = cache.get("daily", {})
                    for date_str, day_data in daily_data.items():
                        total_pv += float(day_data.get("pv", 0.0))
                        total_grid += float(day_data.get("grid", 0.0))
                        total_load += float(day_data.get("load", 0.0))
                        total_essential += float(day_data.get("essential", 0.0))
                        total_total_load += float(day_data.get("total_load", float(day_data.get("load", 0.0)) + float(day_data.get("essential", 0.0))))
                        total_charge += float(day_data.get("charge", 0.0))
                        total_discharge += float(day_data.get("discharge", 0.0))
                        total_saved_kwh += float(day_data.get("saved_kwh", 0.0))
                        total_savings_vnd += float(day_data.get("savings_vnd", 0.0))
                
                _LOGGER.debug(f"Total coordinator: Year {year} - PV: {yearly_totals.get('pv', 0.0):.1f} kWh")
            
            # Add current year's data if we haven't included it yet (cộng dồn năm hiện tại)
            # Only add if current year is not already processed in the loop above
            current_year = dt_util.now().year
            if latest_year is None or latest_year < current_year:
                current_year_data = self._get_current_year_data()
                if current_year_data:
                    total_pv += float(current_year_data.get("pv", 0.0))
                    total_grid += float(current_year_data.get("grid", 0.0))
                    total_load += float(current_year_data.get("load", 0.0))
                    total_essential += float(current_year_data.get("essential", 0.0))
                    total_total_load += float(current_year_data.get("total_load", float(current_year_data.get("load", 0.0)) + float(current_year_data.get("essential", 0.0))))
                    total_charge += float(current_year_data.get("charge", 0.0))
                    total_discharge += float(current_year_data.get("discharge", 0.0))
                    total_saved_kwh += float(current_year_data.get("saved_kwh", 0.0))
                    total_savings_vnd += float(current_year_data.get("savings_vnd", 0.0))
                    latest_year = current_year
            
            _LOGGER.info(f"Total coordinator: Processed {years_processed} years ({earliest_year}-{latest_year})")
            _LOGGER.info(f"Total coordinator: Lifetime totals - PV: {total_pv:.1f} kWh, Charge: {total_charge:.1f} kWh")
            
            return {
                # Lifetime totals (including current year if applicable) - keep full precision
                KEY_TOTAL_PV_KWH: total_pv,
                KEY_TOTAL_GRID_IN_KWH: total_grid,
                KEY_TOTAL_LOAD_KWH: total_load,
                KEY_TOTAL_ESSENTIAL_KWH: total_essential,
                KEY_TOTAL_TOTAL_LOAD_KWH: total_total_load,
                KEY_TOTAL_CHARGE_KWH: total_charge,
                KEY_TOTAL_DISCHARGE_KWH: total_discharge,
                KEY_TOTAL_SAVED_KWH: total_saved_kwh,
                KEY_TOTAL_SAVINGS_VND: total_savings_vnd,
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

    def _get_current_year_data(self) -> Dict[str, float] | None:
        """Get current year's data from yearly coordinator."""
        try:
            if not self._entry_id:
                return None
            
            domain_data = self.hass.data.get(DOMAIN, {})
            entry_data = domain_data.get(self._entry_id, {})
            
            # Get yearly coordinator data (has current month included)
            yearly_coord = entry_data.get("yearly_coordinator")
            if yearly_coord and yearly_coord.data:
                from ..const import (
                    KEY_YEARLY_PV_KWH,
                    KEY_YEARLY_GRID_IN_KWH,
                    KEY_YEARLY_LOAD_KWH,
                    KEY_YEARLY_ESSENTIAL_KWH,
                    KEY_YEARLY_TOTAL_LOAD_KWH,
                    KEY_YEARLY_CHARGE_KWH,
                    KEY_YEARLY_DISCHARGE_KWH,
                    KEY_YEARLY_SAVED_KWH,
                    KEY_YEARLY_SAVINGS_VND,
                )
                return {
                    "pv": float(yearly_coord.data.get(KEY_YEARLY_PV_KWH) or 0.0),
                    "grid": float(yearly_coord.data.get(KEY_YEARLY_GRID_IN_KWH) or 0.0),
                    "load": float(yearly_coord.data.get(KEY_YEARLY_LOAD_KWH) or 0.0),
                    "essential": float(yearly_coord.data.get(KEY_YEARLY_ESSENTIAL_KWH) or 0.0),
                    "total_load": float(yearly_coord.data.get(KEY_YEARLY_TOTAL_LOAD_KWH) or 0.0),
                    "charge": float(yearly_coord.data.get(KEY_YEARLY_CHARGE_KWH) or 0.0),
                    "discharge": float(yearly_coord.data.get(KEY_YEARLY_DISCHARGE_KWH) or 0.0),
                    "saved_kwh": float(yearly_coord.data.get(KEY_YEARLY_SAVED_KWH) or 0.0),
                    "savings_vnd": float(yearly_coord.data.get(KEY_YEARLY_SAVINGS_VND) or 0.0),
                }
            return None
        except Exception:
            return None

