"""Yearly coordinator: summarize year from cache daily/monthly."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..services.aggregator import StatsAggregator
from ..services import cache as cache_io
from ..const import (
    DOMAIN,
    DEFAULT_YEARLY_INTERVAL,
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


_LOGGER = logging.getLogger(__name__)


class YearlyStatsCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str, entry_id: str | None = None) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        self._entry_id = entry_id
        self._last_year: int | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="lumentree_yearly",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone()
            now = dt_util.now(timezone)
            year = now.year
            
            # Check if year has changed - if so, finalize previous year's data
            if self._last_year is not None and self._last_year != year:
                await self._finalize_previous_year(self._last_year)
            
            # Load cache to get monthly arrays (auto-recompute if needed)
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, year, True
            )
            
            # Try to get monthly data from API first (getYearData endpoint)
            # This provides pre-aggregated data for all months, including those missing from daily API
            api_year_data = None
            try:
                api_year_data = await self.aggregator.get_year_data_from_api(year)
                if api_year_data:
                    # Validate that we have meaningful data
                    pv_sum = sum(api_year_data.get("pv", [0.0] * 12))
                    if pv_sum > 0.0:
                        _LOGGER.info(f"Successfully fetched year data from API for {year} (PV total: {pv_sum:.1f} kWh)")
                    else:
                        _LOGGER.warning(f"API returned year data for {year} but PV sum is zero, treating as invalid")
                        api_year_data = None
                else:
                    _LOGGER.warning(f"API returned None for year data for {year}, falling back to cache")
            except Exception as err:
                _LOGGER.warning(f"Failed to get year data from API for {year}: {err}, falling back to cache")
                api_year_data = None
            
            # Ensure monthly arrays are recomputed from daily data for accuracy
            # This ensures all months with daily data are properly aggregated
            # Note: load_year() already auto-recomputes if needed, but we recompute here to ensure
            # consistency after potential API data updates
            if cache.get("daily"):
                cache = cache_io.recompute_aggregates(cache)
                # Save updated cache back
                await self.hass.async_add_executor_job(
                    cache_io.save_year, self.aggregator._device_id, year, cache
                )
            
            # Get monthly arrays for charting (12 months)
            # Priority: API data > cache data
            monthly_data = cache.get("monthly", {})
            
            if api_year_data:
                # Use API data as primary source (it has data for all months, more accurate)
                # API data comes from getYearData which has pre-aggregated monthly totals
                monthly_pv = [round(float(v), 1) for v in api_year_data.get("pv", [0.0] * 12)]
                monthly_grid = [round(float(v), 1) for v in api_year_data.get("grid", [0.0] * 12)]
                monthly_load = [round(float(v), 1) for v in api_year_data.get("load", [0.0] * 12)]
                monthly_essential = [round(float(v), 1) for v in api_year_data.get("essential", [0.0] * 12)]
                monthly_charge = [round(float(v), 1) for v in api_year_data.get("charge", [0.0] * 12)]
                monthly_discharge = [round(float(v), 1) for v in api_year_data.get("discharge", [0.0] * 12)]
                
                # Calculate derived values
                monthly_total_load = [round(load + essential, 1) for load, essential in zip(monthly_load, monthly_essential)]
                monthly_saved_kwh = [round(max(0.0, total - grid), 1) for total, grid in zip(monthly_total_load, monthly_grid)]
                # Calculate savings in VND (using default tariff)
                from ..const import DEFAULT_TARIFF_VND_PER_KWH
                monthly_savings_vnd = [round(saved * DEFAULT_TARIFF_VND_PER_KWH, 0) for saved in monthly_saved_kwh]
                
                # Update cache with API monthly data (more accurate than daily aggregation)
                # This ensures cache has correct monthly arrays from API
                cache["monthly"] = {
                    "pv": monthly_pv,
                    "grid": monthly_grid,
                    "load": monthly_load,
                    "essential": monthly_essential,
                    "total_load": monthly_total_load,
                    "charge": monthly_charge,
                    "discharge": monthly_discharge,
                    "saved_kwh": monthly_saved_kwh,
                    "savings_vnd": monthly_savings_vnd,
                }
                
                # Save updated cache with API monthly data
                await self.hass.async_add_executor_job(
                    cache_io.save_year, self.aggregator._device_id, year, cache
                )
                
                # For current month, only override with cache if cache has more complete data
                # (e.g., includes today's data that API might not have yet)
                current_year = now.year
                if current_year == year:
                    current_month = now.month
                    month_idx = current_month - 1
                    # Check if cache has data for today (more recent than API)
                    today_str = now.strftime("%Y-%m-%d")
                    if today_str in cache.get("daily", {}):
                        current_month_data = await self._get_current_month_data()
                        if current_month_data:
                            # Only update if cache value is higher (includes today)
                            cache_pv = float(current_month_data.get("pv", 0.0))
                            if cache_pv > monthly_pv[month_idx]:
                                monthly_pv[month_idx] = cache_pv
                            cache_grid = float(current_month_data.get("grid", 0.0))
                            if cache_grid > monthly_grid[month_idx]:
                                monthly_grid[month_idx] = cache_grid
                            cache_load = float(current_month_data.get("load", 0.0))
                            if cache_load > monthly_load[month_idx]:
                                monthly_load[month_idx] = cache_load
                            cache_essential = float(current_month_data.get("essential", 0.0))
                            if cache_essential > monthly_essential[month_idx]:
                                monthly_essential[month_idx] = cache_essential
                            # Recalculate derived values for current month
                            total_load_val = current_month_data.get("total_load")
                            if total_load_val is None:
                                total_load_val = monthly_load[month_idx] + monthly_essential[month_idx]
                            monthly_total_load[month_idx] = round(float(total_load_val), 1)
                            monthly_saved_kwh[month_idx] = round(max(0.0, monthly_total_load[month_idx] - monthly_grid[month_idx]), 1)
                            monthly_savings_vnd[month_idx] = round(monthly_saved_kwh[month_idx] * DEFAULT_TARIFF_VND_PER_KWH, 0)
            else:
                # Fallback to cache data
                monthly_pv = monthly_data.get("pv", [0.0] * 12)
                monthly_grid = monthly_data.get("grid", [0.0] * 12)
                monthly_load = monthly_data.get("load", [0.0] * 12)
                monthly_essential = monthly_data.get("essential", [0.0] * 12)
                monthly_total_load = monthly_data.get("total_load", [0.0] * 12)
                monthly_charge = monthly_data.get("charge", [0.0] * 12)
                monthly_discharge = monthly_data.get("discharge", [0.0] * 12)
                monthly_saved_kwh = monthly_data.get("saved_kwh", [0.0] * 12)
                monthly_savings_vnd = monthly_data.get("savings_vnd", [0.0] * 12)
            
            # Calculate yearly totals
            # If we have API data, calculate from monthly arrays (more accurate)
            # Otherwise, use cache (summarize_year)
            if api_year_data:
                # Calculate yearly totals from monthly arrays (from API)
                y = {
                    "pv": round(sum(monthly_pv), 1),
                    "grid": round(sum(monthly_grid), 1),
                    "load": round(sum(monthly_load), 1),
                    "essential": round(sum(monthly_essential), 1),
                    "total_load": round(sum(monthly_total_load), 1),
                    "charge": round(sum(monthly_charge), 1),
                    "discharge": round(sum(monthly_discharge), 1),
                    "saved_kwh": round(sum(monthly_saved_kwh), 1),
                    "savings_vnd": round(sum(monthly_savings_vnd), 0),
                }
                
                # For current month, prefer cache data if available (more accurate, includes today)
                current_year = now.year
                if current_year == year:
                    current_month = now.month
                    current_month_data = await self._get_current_month_data()
                    
                    if current_month_data:
                        month_idx = current_month - 1
                        # Replace current month with real-time data
                        monthly_pv[month_idx] = float(current_month_data.get("pv", 0.0))
                        monthly_grid[month_idx] = float(current_month_data.get("grid", 0.0))
                        monthly_load[month_idx] = float(current_month_data.get("load", 0.0))
                        monthly_essential[month_idx] = float(current_month_data.get("essential", 0.0))
                        # Ensure total_load is calculated if missing
                        total_load_val = current_month_data.get("total_load")
                        if total_load_val is None:
                            total_load_val = monthly_load[month_idx] + monthly_essential[month_idx]
                        monthly_total_load[month_idx] = float(total_load_val)
                        monthly_charge[month_idx] = float(current_month_data.get("charge", 0.0))
                        monthly_discharge[month_idx] = float(current_month_data.get("discharge", 0.0))
                        # Ensure saved_kwh and savings_vnd are calculated if missing
                        saved_kwh_val = current_month_data.get("saved_kwh")
                        if saved_kwh_val is None:
                            saved_kwh_val = max(0.0, monthly_total_load[month_idx] - monthly_grid[month_idx])
                        monthly_saved_kwh[month_idx] = float(saved_kwh_val)
                        savings_vnd_val = current_month_data.get("savings_vnd")
                        if savings_vnd_val is None:
                            from ..const import DEFAULT_TARIFF_VND_PER_KWH
                            savings_vnd_val = monthly_saved_kwh[month_idx] * DEFAULT_TARIFF_VND_PER_KWH
                        monthly_savings_vnd[month_idx] = float(savings_vnd_val)
                        
                        # Recalculate yearly totals with updated current month
                        y = {
                            "pv": round(sum(monthly_pv), 1),
                            "grid": round(sum(monthly_grid), 1),
                            "load": round(sum(monthly_load), 1),
                            "essential": round(sum(monthly_essential), 1),
                            "total_load": round(sum(monthly_total_load), 1),
                            "charge": round(sum(monthly_charge), 1),
                            "discharge": round(sum(monthly_discharge), 1),
                            "saved_kwh": round(sum(monthly_saved_kwh), 1),
                            "savings_vnd": round(sum(monthly_savings_vnd), 0),
                        }
            else:
                # Fallback: Summarize year totals from cache (các tháng đã chốt)
                y = await self.aggregator.summarize_year(year)
                
                # Replace current month's data if we're in the current year (tránh double counting)
                # yearly_total đã bao gồm tháng hiện tại (các ngày đã chốt), cần thay thế bằng tổng đầy đủ
                current_year = now.year
                if current_year == year:
                    current_month = now.month
                    current_month_data = await self._get_current_month_data()
                    
                    # Get current month from cache (chỉ các ngày đã chốt)
                    cached_month_data = await self.aggregator.summarize_month(year, current_month)
                    
                    if current_month_data:
                        # Trừ đi phần tháng hiện tại đã có trong yearly_total (tránh double count)
                        y["pv"] = y.get("pv", 0.0) - cached_month_data.get("pv", 0.0) + float(current_month_data.get("pv", 0.0))
                        y["grid"] = y.get("grid", 0.0) - cached_month_data.get("grid", 0.0) + float(current_month_data.get("grid", 0.0))
                        y["load"] = y.get("load", 0.0) - cached_month_data.get("load", 0.0) + float(current_month_data.get("load", 0.0))
                        y["essential"] = y.get("essential", 0.0) - cached_month_data.get("essential", 0.0) + float(current_month_data.get("essential", 0.0))
                        y["total_load"] = y.get("total_load", 0.0) - cached_month_data.get("total_load", 0.0) + float(current_month_data.get("total_load", 0.0))
                        y["saved_kwh"] = y.get("saved_kwh", 0.0) - cached_month_data.get("saved_kwh", 0.0) + float(current_month_data.get("saved_kwh", 0.0))
                        y["savings_vnd"] = y.get("savings_vnd", 0.0) - cached_month_data.get("savings_vnd", 0.0) + float(current_month_data.get("savings_vnd", 0.0))
                        y["charge"] = y.get("charge", 0.0) - cached_month_data.get("charge", 0.0) + float(current_month_data.get("charge", 0.0))
                        y["discharge"] = y.get("discharge", 0.0) - cached_month_data.get("discharge", 0.0) + float(current_month_data.get("discharge", 0.0))
            
            # Update last_year tracking
            self._last_year = year
            
            return {
                # Yearly totals (including current month if current year)
                KEY_YEARLY_PV_KWH: y.get("pv", 0.0),
                KEY_YEARLY_GRID_IN_KWH: y.get("grid", 0.0),
                KEY_YEARLY_LOAD_KWH: y.get("load", 0.0),
                KEY_YEARLY_ESSENTIAL_KWH: y.get("essential", 0.0),
                KEY_YEARLY_TOTAL_LOAD_KWH: y.get("total_load", 0.0),
                KEY_YEARLY_CHARGE_KWH: y.get("charge", 0.0),
                KEY_YEARLY_DISCHARGE_KWH: y.get("discharge", 0.0),
                KEY_YEARLY_SAVED_KWH: y.get("saved_kwh", 0.0),
                KEY_YEARLY_SAVINGS_VND: y.get("savings_vnd", 0.0),
                # Monthly arrays for charting (12 months)
                "monthly_pv": monthly_pv,
                "monthly_grid": monthly_grid,
                "monthly_load": monthly_load,
                "monthly_essential": monthly_essential,
                "monthly_total_load": monthly_total_load,
                "monthly_charge": monthly_charge,
                "monthly_discharge": monthly_discharge,
                "monthly_saved_kwh": monthly_saved_kwh,
                "monthly_savings_vnd": monthly_savings_vnd,
                "year": year,
            }
        except Exception as err:
            _LOGGER.exception("Unexpected yearly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _finalize_previous_year(self, previous_year: int) -> None:
        """Finalize previous year's data by ensuring cache is up-to-date."""
        try:
            _LOGGER.info(f"Year changed: Finalizing data for year {previous_year}")
            # Load cache and ensure aggregates are recomputed
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, previous_year
            )
            
            # Recompute aggregates to ensure monthly and yearly totals are accurate
            cache = cache_io.recompute_aggregates(cache)
            
            # Save finalized cache
            await self.hass.async_add_executor_job(
                cache_io.save_year, self.aggregator._device_id, previous_year, cache
            )
            
            _LOGGER.info(f"Finalized data for year {previous_year}")
        except Exception as err:
            _LOGGER.warning(f"Failed to finalize year {previous_year}: {err}")
            # Don't raise - this is a best-effort operation

    async def _get_current_month_data(self) -> Dict[str, float] | None:
        """Get current month's data from monthly coordinator or calculate from daily coordinator."""
        try:
            if not self._entry_id:
                return None
            
            domain_data = self.hass.data.get(DOMAIN, {})
            entry_data = domain_data.get(self._entry_id, {})
            
            # Try monthly coordinator first (has today included)
            monthly_coord = entry_data.get("monthly_coordinator")
            if monthly_coord and monthly_coord.data:
                from ..const import (
                    KEY_MONTHLY_PV_KWH,
                    KEY_MONTHLY_GRID_IN_KWH,
                    KEY_MONTHLY_LOAD_KWH,
                    KEY_MONTHLY_ESSENTIAL_KWH,
                    KEY_MONTHLY_CHARGE_KWH,
                    KEY_MONTHLY_DISCHARGE_KWH,
                )
                from ..const import (
                    KEY_MONTHLY_TOTAL_LOAD_KWH,
                    KEY_MONTHLY_SAVED_KWH,
                    KEY_MONTHLY_SAVINGS_VND,
                )
                load_val = float(monthly_coord.data.get(KEY_MONTHLY_LOAD_KWH) or 0.0)
                essential_val = float(monthly_coord.data.get(KEY_MONTHLY_ESSENTIAL_KWH) or 0.0)
                total_load_val = float(monthly_coord.data.get(KEY_MONTHLY_TOTAL_LOAD_KWH) or (load_val + essential_val))
                return {
                    "pv": float(monthly_coord.data.get(KEY_MONTHLY_PV_KWH) or 0.0),
                    "grid": float(monthly_coord.data.get(KEY_MONTHLY_GRID_IN_KWH) or 0.0),
                    "load": load_val,
                    "essential": essential_val,
                    "total_load": total_load_val,
                    "charge": float(monthly_coord.data.get(KEY_MONTHLY_CHARGE_KWH) or 0.0),
                    "discharge": float(monthly_coord.data.get(KEY_MONTHLY_DISCHARGE_KWH) or 0.0),
                    "saved_kwh": float(monthly_coord.data.get(KEY_MONTHLY_SAVED_KWH) or 0.0),
                    "savings_vnd": float(monthly_coord.data.get(KEY_MONTHLY_SAVINGS_VND) or 0.0),
                }
            
            # Fallback: calculate from cache + today
            from ..services import cache as cache_io
            now = dt_util.now(dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone())
            year = now.year
            month = now.month
            
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, year
            )
            m = cache_io.summarize_month(cache, month)
            
            # Add today if current month
            daily_coord = entry_data.get("daily_coordinator")
            if daily_coord and daily_coord.data:
                today = now.date()
                if today.month == month:
                    load_today = float(daily_coord.data.get("load_today") or 0.0)
                    essential_today = float(daily_coord.data.get("essential_today") or 0.0)
                    total_load_today = load_today + essential_today
                    grid_today = float(daily_coord.data.get("grid_in_today") or 0.0)
                    saved_kwh_today = max(0.0, total_load_today - grid_today)
                    from ..const import DEFAULT_TARIFF_VND_PER_KWH
                    savings_vnd_today = saved_kwh_today * DEFAULT_TARIFF_VND_PER_KWH
                    
                    m["pv"] = m.get("pv", 0.0) + float(daily_coord.data.get("pv_today") or 0.0)
                    m["grid"] = m.get("grid", 0.0) + grid_today
                    m["load"] = m.get("load", 0.0) + load_today
                    m["essential"] = m.get("essential", 0.0) + essential_today
                    m["total_load"] = m.get("total_load", 0.0) + total_load_today
                    m["charge"] = m.get("charge", 0.0) + float(daily_coord.data.get("charge_today") or 0.0)
                    m["discharge"] = m.get("discharge", 0.0) + float(daily_coord.data.get("discharge_today") or 0.0)
                    m["saved_kwh"] = m.get("saved_kwh", 0.0) + saved_kwh_today
                    m["savings_vnd"] = m.get("savings_vnd", 0.0) + savings_vnd_today
            
            # Ensure total_load is set if missing
            if "total_load" not in m:
                m["total_load"] = m.get("load", 0.0) + m.get("essential", 0.0)
            
            # Ensure saved_kwh and savings_vnd are set if missing
            if "saved_kwh" not in m:
                total_load_val = m.get("total_load", 0.0)
                grid_val = m.get("grid", 0.0)
                m["saved_kwh"] = max(0.0, total_load_val - grid_val)
            if "savings_vnd" not in m:
                from ..const import DEFAULT_TARIFF_VND_PER_KWH
                m["savings_vnd"] = m.get("saved_kwh", 0.0) * DEFAULT_TARIFF_VND_PER_KWH
            
            return m
        except Exception:
            return None


