"""Yearly coordinator: summarize year from cache daily/monthly."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_YEARLY_INTERVAL,
    DOMAIN,
    KEY_MONTHLY_CHARGE_KWH,
    KEY_MONTHLY_DISCHARGE_KWH,
    KEY_MONTHLY_ESSENTIAL_KWH,
    KEY_MONTHLY_GRID_IN_KWH,
    KEY_MONTHLY_LOAD_KWH,
    KEY_MONTHLY_PV_KWH,
    KEY_MONTHLY_SAVED_KWH,
    KEY_MONTHLY_SAVINGS_VND,
    KEY_MONTHLY_TOTAL_LOAD_KWH,
    KEY_YEARLY_CHARGE_KWH,
    KEY_YEARLY_DISCHARGE_KWH,
    KEY_YEARLY_ESSENTIAL_KWH,
    KEY_YEARLY_GRID_IN_KWH,
    KEY_YEARLY_LOAD_KWH,
    KEY_YEARLY_PV_KWH,
    KEY_YEARLY_SAVED_KWH,
    KEY_YEARLY_SAVINGS_VND,
    KEY_YEARLY_TOTAL_LOAD_KWH,
    get_timezone,
)
from ..services import cache as cache_io
from ..services.aggregator import StatsAggregator

_LOGGER = logging.getLogger(__name__)

# Cache key -> (monthly coordinator key, yearly sensor key).
_METRICS: dict[str, tuple[str, str]] = {
    "pv": (KEY_MONTHLY_PV_KWH, KEY_YEARLY_PV_KWH),
    "grid": (KEY_MONTHLY_GRID_IN_KWH, KEY_YEARLY_GRID_IN_KWH),
    "load": (KEY_MONTHLY_LOAD_KWH, KEY_YEARLY_LOAD_KWH),
    "essential": (KEY_MONTHLY_ESSENTIAL_KWH, KEY_YEARLY_ESSENTIAL_KWH),
    "total_load": (KEY_MONTHLY_TOTAL_LOAD_KWH, KEY_YEARLY_TOTAL_LOAD_KWH),
    "charge": (KEY_MONTHLY_CHARGE_KWH, KEY_YEARLY_CHARGE_KWH),
    "discharge": (KEY_MONTHLY_DISCHARGE_KWH, KEY_YEARLY_DISCHARGE_KWH),
    "saved_kwh": (KEY_MONTHLY_SAVED_KWH, KEY_YEARLY_SAVED_KWH),
    "savings_vnd": (KEY_MONTHLY_SAVINGS_VND, KEY_YEARLY_SAVINGS_VND),
}


class YearlyStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Year totals: finished months from the cache, this month from the monthly coordinator.

    This used to take the monthly figures from getYearData and write them into
    the year cache every five minutes.  The captured responses in docs/ show
    that endpoint answering year=2026 with 2025's twelve months, so the
    "this year" sensors were mostly last year's numbers, and the cache's
    monthly arrays were overwritten with them on every refresh.
    """

    __slots__ = ("aggregator", "device_sn", "_entry_id", "_last_year")

    def __init__(
        self,
        hass: HomeAssistant,
        aggregator: StatsAggregator,
        device_sn: str,
        entry_id: str | None = None,
    ) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        self._entry_id = entry_id
        self._last_year: int | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"lumentree_yearly_{device_sn}",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            now = dt_util.now(get_timezone(self.hass))
            year = now.year
            month_idx = now.month - 1
            today_str = now.date().isoformat()

            # Check if year has changed - if so, finalize previous year's data
            if self._last_year is not None and self._last_year != year:
                await self._finalize_previous_year(self._last_year)

            device_id = self.aggregator._device_id

            def _load_monthly() -> dict[str, list[float]]:
                cache = cache_io.load_year(device_id, year, auto_recompute=False)
                # Repair the stored aggregates once if they no longer match the
                # daily rows (earlier versions overwrote them with getYearData).
                if cache.get("daily") and cache.get("monthly") != cache_io.monthly_totals(cache):
                    cache_io.save_year(device_id, year, cache_io.recompute_aggregates(cache))
                return cache_io.monthly_totals(cache, before=today_str)

            monthly = await self.hass.async_add_executor_job(_load_monthly)

            # The current month, today included, as the monthly coordinator
            # publishes it.  Without it the month keeps only its finished days.
            current = self._current_month_totals(year, now.month)
            if current is not None:
                for key, (monthly_key, _yearly_key) in _METRICS.items():
                    monthly[key][month_idx] = float(current.get(monthly_key) or 0.0)

            self._last_year = year

            result: dict[str, Any] = {}
            for key, (_monthly_key, yearly_key) in _METRICS.items():
                result[yearly_key] = round(sum(monthly[key]), 0 if key == "savings_vnd" else 2)
                result[f"monthly_{key}"] = monthly[key]
            result["year"] = year
            return result
        except Exception as err:
            _LOGGER.exception("Unexpected yearly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _finalize_previous_year(self, previous_year: int) -> None:
        """Finalize previous year's data by ensuring cache is up-to-date."""
        try:
            _LOGGER.info(f"Year changed: Finalizing data for year {previous_year}")

            # Load, recompute and save in one executor job: recompute_aggregates
            # walks the whole daily map, which must not happen on the event loop.
            # The load and save around it were already offloaded.
            def _finalize() -> None:
                c = cache_io.load_year(
                    self.aggregator._device_id, previous_year, auto_recompute=False
                )
                cache_io.save_year(
                    self.aggregator._device_id,
                    previous_year,
                    cache_io.recompute_aggregates(c),
                )

            await self.hass.async_add_executor_job(_finalize)

            _LOGGER.info(f"Finalized data for year {previous_year}")
        except Exception as err:
            _LOGGER.warning(f"Failed to finalize year {previous_year}: {err}")
            # Don't raise - this is a best-effort operation

    def _current_month_totals(self, year: int, month: int) -> dict[str, Any] | None:
        """The monthly coordinator's data, if it describes ``year``-``month``."""
        if not self._entry_id:
            return None
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        data = getattr(entry_data.get("monthly_coordinator"), "data", None)
        if not data or data.get("year") != year or data.get("month") != month:
            return None
        return dict(data)
