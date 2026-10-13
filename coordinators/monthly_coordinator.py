"""Monthly coordinator: ensure month aggregates via cache and on-demand fill."""

from __future__ import annotations

import calendar
import datetime as dt
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import (
    ATTR_SOURCE_DATE,
    DEFAULT_MONTHLY_INTERVAL,
    DEFAULT_TARIFF_VND_PER_KWH,
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
    get_timezone,
)
from ..services import cache as cache_io
from ..services.aggregator import StatsAggregator

_LOGGER = logging.getLogger(__name__)

# Daily-array name, cache key, and the sensor key its month total feeds.
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("daily_pv", "pv", KEY_MONTHLY_PV_KWH),
    ("daily_charge", "charge", KEY_MONTHLY_CHARGE_KWH),
    ("daily_discharge", "discharge", KEY_MONTHLY_DISCHARGE_KWH),
    ("daily_grid", "grid", KEY_MONTHLY_GRID_IN_KWH),
    ("daily_load", "load", KEY_MONTHLY_LOAD_KWH),
    ("daily_essential", "essential", KEY_MONTHLY_ESSENTIAL_KWH),
    ("daily_total_load", "total_load", KEY_MONTHLY_TOTAL_LOAD_KWH),
    ("daily_saved_kwh", "saved_kwh", KEY_MONTHLY_SAVED_KWH),
    ("daily_savings_vnd", "savings_vnd", KEY_MONTHLY_SAVINGS_VND),
)


def _cached_day(day_data: dict[str, Any]) -> dict[str, float]:
    """A cached day's values, deriving the ones older caches did not store."""
    load_val = float(day_data.get("load", 0.0))
    essential_val = float(day_data.get("essential", 0.0))
    grid_val = float(day_data.get("grid", 0.0))
    total_load = float(day_data.get("total_load", load_val + essential_val))
    saved_kwh = float(day_data.get("saved_kwh", max(0.0, total_load - grid_val)))
    return {
        "pv": float(day_data.get("pv", 0.0)),
        "charge": float(day_data.get("charge", 0.0)),
        "discharge": float(day_data.get("discharge", 0.0)),
        "grid": grid_val,
        "load": load_val,
        "essential": essential_val,
        "total_load": total_load,
        "saved_kwh": saved_kwh,
        "savings_vnd": float(day_data.get("savings_vnd", saved_kwh * DEFAULT_TARIFF_VND_PER_KWH)),
    }


def _live_day(today_data: dict[str, Any]) -> dict[str, float]:
    """Today's values from the daily coordinator, in cache keys."""
    load_val = float(today_data.get("load_today") or 0.0)
    essential_val = float(today_data.get("essential_today") or 0.0)
    grid_val = float(today_data.get("grid_in_today") or 0.0)
    saved_kwh = max(0.0, load_val + essential_val - grid_val)
    return {
        "pv": float(today_data.get("pv_today") or 0.0),
        "charge": float(today_data.get("charge_today") or 0.0),
        "discharge": float(today_data.get("discharge_today") or 0.0),
        "grid": grid_val,
        "load": load_val,
        "essential": essential_val,
        "total_load": load_val + essential_val,
        "saved_kwh": saved_kwh,
        "savings_vnd": saved_kwh * DEFAULT_TARIFF_VND_PER_KWH,
    }


class MonthlyStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    __slots__ = ("aggregator", "device_sn", "_entry_id", "_last_month")

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
        self._last_month: tuple[int, int] | None = None  # (year, month)
        super().__init__(
            hass,
            _LOGGER,
            name=f"lumentree_monthly_{device_sn}",
            update_interval=dt.timedelta(seconds=DEFAULT_MONTHLY_INTERVAL),
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            now = dt_util.now(get_timezone(self.hass))
            year = now.year
            month = now.month
            today = now.date()

            # Check if month has changed - if so, finalize previous month's data
            if self._last_month is not None and self._last_month != (year, month):
                prev_year, prev_month = self._last_month
                await self._finalize_previous_month(prev_year, prev_month)

            cache = await self.hass.async_add_executor_job(
                cache_io.load_year, self.aggregator._device_id, year, True
            )
            daily_cache = cache.get("daily", {})
            live_today = self._get_today_data_from_daily_coord(today.isoformat())

            # One array per metric, a slot per day.  Past days come from the
            # cache, today from the live daily coordinator, later days are 0.
            # A cache row for today or later is ignored: it can only be a
            # partial reading written before the day ended, and summing it
            # next to the live value counted today twice.
            days_in_month = calendar.monthrange(year, month)[1]
            arrays: dict[str, list[float]] = {name: [] for name, _key, _sensor in _SERIES}
            for day in range(1, days_in_month + 1):
                date = dt.date(year, month, day)
                if date < today:
                    values = _cached_day(daily_cache.get(date.isoformat(), {}))
                elif date == today and live_today:
                    values = _live_day(live_today)
                else:
                    values = {}
                for name, key, _sensor in _SERIES:
                    arrays[name].append(values.get(key, 0.0))

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "Monthly %s %s-%02d: %d cached days, live today: %s",
                    self.device_sn,
                    year,
                    month,
                    sum(1 for d in daily_cache if d.startswith(f"{year}-{month:02d}-")),
                    bool(live_today),
                )

            self._last_month = (year, month)

            # The totals are the sums of the arrays published beside them, so
            # a sensor and its own chart attribute cannot disagree.
            result: dict[str, Any] = {}
            for name, key, sensor_key in _SERIES:
                total = sum(arrays[name])
                result[sensor_key] = round(total, 0 if key == "savings_vnd" else 2)
            result.update(arrays)
            result.update({"days_in_month": days_in_month, "year": year, "month": month})
            return result
        except TimeoutError as err:
            raise UpdateFailed("Timeout monthly") from err
        except Exception as err:
            _LOGGER.exception("Unexpected monthly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _finalize_previous_month(self, previous_year: int, previous_month: int) -> None:
        """Finalize previous month's data by ensuring cache is up-to-date."""
        try:
            _LOGGER.info(f"Month changed: Finalizing data for {previous_year}-{previous_month:02d}")

            # Load, recompute and save in one executor job.  recompute_aggregates
            # walks the whole daily map of the year, so running it on the event
            # loop blocks every entity update for the duration.  The load and
            # save around it were already offloaded.
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

            _LOGGER.info(f"Finalized data for month {previous_year}-{previous_month:02d}")
        except Exception as err:
            _LOGGER.warning(f"Failed to finalize month {previous_year}-{previous_month:02d}: {err}")
            # Don't raise - this is a best-effort operation

    def _get_today_data_from_daily_coord(self, today_str: str) -> dict[str, Any] | None:
        """Today's live data from the daily coordinator, if it is today's.

        Right after midnight the daily coordinator still holds yesterday's
        final totals until its next refresh; adding those as "today" booked
        yesterday twice -- into the next month, on the first of the month.
        """
        if not self._entry_id:
            return None
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        daily_coord = entry_data.get("daily_coordinator")
        data = getattr(daily_coord, "data", None)
        if not data or data.get(ATTR_SOURCE_DATE) != today_str:
            return None
        return dict(data)
