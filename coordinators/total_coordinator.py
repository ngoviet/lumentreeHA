"""Total coordinator: calculate lifetime totals from all cached data."""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import (
    DEFAULT_YEARLY_INTERVAL,  # Use same interval as yearly
    DOMAIN,
    KEY_TOTAL_CHARGE_KWH,
    KEY_TOTAL_DISCHARGE_KWH,
    KEY_TOTAL_ESSENTIAL_KWH,
    KEY_TOTAL_GRID_IN_KWH,
    KEY_TOTAL_LOAD_KWH,
    KEY_TOTAL_PV_KWH,
    KEY_TOTAL_SAVED_KWH,
    KEY_TOTAL_SAVINGS_VND,
    KEY_TOTAL_TOTAL_LOAD_KWH,
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

# How many years back from the current one are summed.
_YEARS_BACK = 10

# Cache key -> (yearly coordinator key, lifetime sensor key).
_METRICS: dict[str, tuple[str, str]] = {
    "pv": (KEY_YEARLY_PV_KWH, KEY_TOTAL_PV_KWH),
    "grid": (KEY_YEARLY_GRID_IN_KWH, KEY_TOTAL_GRID_IN_KWH),
    "load": (KEY_YEARLY_LOAD_KWH, KEY_TOTAL_LOAD_KWH),
    "essential": (KEY_YEARLY_ESSENTIAL_KWH, KEY_TOTAL_ESSENTIAL_KWH),
    "total_load": (KEY_YEARLY_TOTAL_LOAD_KWH, KEY_TOTAL_TOTAL_LOAD_KWH),
    "charge": (KEY_YEARLY_CHARGE_KWH, KEY_TOTAL_CHARGE_KWH),
    "discharge": (KEY_YEARLY_DISCHARGE_KWH, KEY_TOTAL_DISCHARGE_KWH),
    "saved_kwh": (KEY_YEARLY_SAVED_KWH, KEY_TOTAL_SAVED_KWH),
    "savings_vnd": (KEY_YEARLY_SAVINGS_VND, KEY_TOTAL_SAVINGS_VND),
}


def _year_totals(cache: dict[str, Any], before: str | None = None) -> dict[str, float] | None:
    """One year's totals from its daily rows, or None when it has none."""
    if not cache.get("daily"):
        return None
    monthly = cache_io.monthly_totals(cache, before=before)
    return {key: float(sum(vals)) for key, vals in monthly.items()}


class TotalStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lifetime totals: past years from the cache, this year from the yearly coordinator."""

    __slots__ = ("aggregator", "device_sn", "_entry_id", "_past_years")

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
        # year -> (file mtime, totals).  A finished year's file only changes
        # when a backfill touches it, so it is re-read only then instead of
        # parsing ten JSON files every five minutes.
        self._past_years: dict[int, tuple[float, dict[str, float] | None]] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=f"lumentree_total_{device_sn}",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
            always_update=False,
        )

    def _load_years(self, current_year: int, today_str: str) -> dict[int, dict[str, float]]:
        """Totals per year with data (blocking: runs in the executor)."""
        device_id = self.aggregator._device_id
        totals: dict[int, dict[str, float]] = {}
        for year in range(current_year - _YEARS_BACK + 1, current_year + 1):
            path = cache_io.cache_path(device_id, year)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = -1.0
            if year < current_year:
                memo = self._past_years.get(year)
                if memo is None or memo[0] != mtime:
                    cache = cache_io.load_year(device_id, year, auto_recompute=False)
                    memo = (mtime, _year_totals(cache))
                    self._past_years[year] = memo
                year_totals = memo[1]
            else:
                cache = cache_io.load_year(device_id, year, auto_recompute=False)
                year_totals = _year_totals(cache, before=today_str)
            if year_totals is not None:
                totals[year] = year_totals
        return totals

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            now = dt_util.now(get_timezone(self.hass))
            current_year = now.year
            years = await self.hass.async_add_executor_job(
                self._load_years, current_year, now.date().isoformat()
            )

            # The current year, live month included, as the yearly coordinator
            # publishes it.  Counted once: this used to be added *on top of*
            # the cached current year whenever more than one year was cached
            # (the "latest year" it checked was really the oldest).
            live = self._current_year_totals(current_year)
            if live is not None:
                years[current_year] = {
                    key: float(live.get(yearly_key) or 0.0)
                    for key, (yearly_key, _total_key) in _METRICS.items()
                }

            result: dict[str, Any] = {}
            for key, (_yearly_key, total_key) in _METRICS.items():
                result[total_key] = sum(year_totals.get(key, 0.0) for year_totals in years.values())

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Total %s: years %s, PV %.1f kWh",
                    self.device_sn,
                    sorted(years),
                    result[KEY_TOTAL_PV_KWH],
                )

            result.update(
                {
                    "years_processed": len(years),
                    "earliest_year": min(years) if years else None,
                    "latest_year": max(years) if years else None,
                    "last_updated": now.isoformat(),
                }
            )
            return result
        except Exception as err:
            _LOGGER.exception("Unexpected total update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _current_year_totals(self, year: int) -> dict[str, Any] | None:
        """The yearly coordinator's data, if it describes ``year``."""
        if not self._entry_id:
            return None
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        data = getattr(entry_data.get("yearly_coordinator"), "data", None)
        if not data or data.get("year") != year:
            return None
        return dict(data)
