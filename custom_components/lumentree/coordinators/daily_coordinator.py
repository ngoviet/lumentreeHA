"""Daily coordinator for fetching today's HTTP stats (every 5 minutes)."""

from __future__ import annotations

import datetime as dt
import asyncio
import logging
from typing import Dict, Optional, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..core.api_client import LumentreeHttpApiClient
from ..core.exceptions import ApiException, AuthException
from ..const import DEFAULT_DAILY_INTERVAL, DEFAULT_TARIFF_VND_PER_KWH
from ..services.aggregator import StatsAggregator
from ..services import cache as cache_io


_LOGGER = logging.getLogger(__name__)


class DailyStatsCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: LumentreeHttpApiClient,
        aggregator: StatsAggregator,
        device_sn: str,
        interval_sec: int | None = None
    ) -> None:
        self.api = api
        self.aggregator = aggregator
        self.device_sn = device_sn
        self._last_date: Optional[str] = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"lumentree_daily_{device_sn}",
            update_interval=dt.timedelta(seconds=(interval_sec or DEFAULT_DAILY_INTERVAL)),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch today's data from API with error handling and recovery."""
        try:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone()
            today_str = dt_util.now(timezone).strftime("%Y-%m-%d")
            
            # Check if day has changed - if so, save yesterday's data to cache
            if self._last_date is not None and self._last_date != today_str:
                await self._save_yesterday_to_cache(self._last_date)
            
            # Fetch today's data with extended timeout (retry logic is in API client)
            async with asyncio.timeout(90):  # Extended timeout for retries
                new_data = await self.api.get_daily_stats(self.device_sn, today_str)
            
            # Calculate savings: Energy saved = Total Load - Grid Import
            # This represents energy not purchased from grid (from PV + battery discharge)
            total_load = float(new_data.get("total_load_today") or 0.0)
            grid_in = float(new_data.get("grid_in_today") or 0.0)
            saved_kwh = max(0.0, total_load - grid_in)  # Ensure non-negative
            savings_vnd = saved_kwh * DEFAULT_TARIFF_VND_PER_KWH
            
            # Add savings to data - round to match API precision
            new_data["saved_kwh"] = round(saved_kwh, 1)
            new_data["savings_vnd"] = round(savings_vnd, 0)  # Money: no decimals
            
            # Update last_date tracking
            self._last_date = today_str
            
            return new_data
            
        except AuthException as err:
            # Auth errors - don't retry, requires user intervention
            _LOGGER.error(f"Authentication failed: {err}. Please check configuration.")
            raise UpdateFailed(f"Auth error: {err}") from err
            
        except ApiException as err:
            # Network/API errors - check if we can use cached data as fallback
            error_msg = str(err).lower()
            is_network_error = any(keyword in error_msg for keyword in [
                "connection failed", "server may be down", "network unavailable",
                "timeout", "unreachable", "refused"
            ])
            
            if is_network_error:
                _LOGGER.warning(
                    f"Network error fetching daily data: {err}. "
                    "Will retry automatically on next update interval."
                )
            
            # Raise UpdateFailed - HA's DataUpdateCoordinator will automatically retry
            # on next interval, and will keep using last known good data
            raise UpdateFailed(f"API error: {err}") from err
            
        except asyncio.TimeoutError as err:
            _LOGGER.warning(
                f"Timeout fetching daily data after all retries. "
                "Will retry automatically on next update interval."
            )
            raise UpdateFailed("Timeout fetching daily data") from err
            
        except Exception as err:
            _LOGGER.exception("Unexpected daily update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _save_yesterday_to_cache(self, yesterday_date: str) -> None:
        """Save yesterday's data to cache by querying API for final data.
        
        Instead of using data from memory (which may be incomplete if different
        endpoints finalize at different times), we query the API one more time
        for yesterday's date to ensure we get the final, finalized data from server.
        """
        try:
            
            year = int(yesterday_date[:4])
            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, year
            )
            
            # Skip if already exists (avoid unnecessary API call)
            if yesterday_date in cache.get("daily", {}):
                _LOGGER.debug(f"Data for {yesterday_date} already exists in cache, skipping")
                return
            
            # Query API one more time with yesterday's date to get finalized data
            # This ensures all 6 data types are synchronized from the same API call
            _LOGGER.info(f"Fetching finalized data for {yesterday_date} from API...")
            async with asyncio.timeout(60):
                finalized_data = await self.api.get_daily_stats(self.device_sn, yesterday_date)
            
            # Extract values from API response format to cache format
            # API returns integers divided by 10, so precision is 1 decimal place for kWh
            load_val = float(finalized_data.get("load_today") or 0.0)
            essential_val = float(finalized_data.get("essential_today") or 0.0)
            # Use total_load_today from API if available (most accurate), otherwise calculate from raw values
            total_load_val = float(finalized_data.get("total_load_today") or 0.0)
            if total_load_val == 0.0 and (load_val > 0.0 or essential_val > 0.0):
                # Calculate from raw values, then round to match API precision (1 decimal)
                total_load_val = round(load_val + essential_val, 1)
            else:
                total_load_val = round(total_load_val, 1)
            
            grid_val = round(float(finalized_data.get("grid_in_today") or 0.0), 1)
            saved_kwh = max(0.0, round(total_load_val - grid_val, 1))
            savings_vnd = round(saved_kwh * DEFAULT_TARIFF_VND_PER_KWH, 0)  # Money: no decimals
            values = {
                "pv": round(float(finalized_data.get("pv_today") or 0.0), 1),
                "grid": grid_val,
                "load": round(load_val, 1),
                "essential": round(essential_val, 1),
                "total_load": total_load_val,
                "charge": round(float(finalized_data.get("charge_today") or 0.0), 1),
                "discharge": round(float(finalized_data.get("discharge_today") or 0.0), 1),
                "saved_kwh": saved_kwh,
                "savings_vnd": savings_vnd,
            }
            
            # Check if data is meaningful (not all zeros)
            is_empty = all(abs(v) < 1e-6 for v in values.values())
            
            if is_empty:
                _LOGGER.debug(f"Finalized data for {yesterday_date} is empty, marking as empty")
                cache = cache_io.mark_empty(cache, yesterday_date)
                await self.hass.async_add_executor_job(
                    cache_io.save_year, self.aggregator._device_id, year, cache
                )
                return
            
            # Update cache with finalized data
            cache, _m, _ = cache_io.update_daily(cache, yesterday_date, values)
            cache.setdefault("meta", {})["last_backfill_date"] = yesterday_date
            
            # Save cache
            await self.hass.async_add_executor_job(
                cache_io.save_year, self.aggregator._device_id, year, cache
            )
            
            _LOGGER.info(
                f"Auto-saved finalized data for {yesterday_date} to cache: "
                f"PV={values['pv']:.2f}kWh, Grid={values['grid']:.2f}kWh, "
                f"Load={values['load']:.2f}kWh, Charge={values['charge']:.2f}kWh, "
                f"Discharge={values['discharge']:.2f}kWh"
            )
        except Exception as err:
            _LOGGER.warning(f"Failed to auto-save finalized data for {yesterday_date}: {err}")
            # Don't raise - this is a best-effort operation


