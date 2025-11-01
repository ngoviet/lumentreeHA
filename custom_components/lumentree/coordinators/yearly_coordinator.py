"""Yearly coordinator: summarize year from cache daily/monthly."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..services.aggregator import StatsAggregator
from ..const import (
    DEFAULT_YEARLY_INTERVAL,
    KEY_YEARLY_PV_KWH,
    KEY_YEARLY_GRID_IN_KWH,
    KEY_YEARLY_LOAD_KWH,
    KEY_YEARLY_ESSENTIAL_KWH,
    KEY_YEARLY_CHARGE_KWH,
    KEY_YEARLY_DISCHARGE_KWH,
)


_LOGGER = logging.getLogger(__name__)


class YearlyStatsCoordinator(DataUpdateCoordinator[Dict[str, float]]):
    def __init__(self, hass: HomeAssistant, aggregator: StatsAggregator, device_sn: str) -> None:
        self.aggregator = aggregator
        self.device_sn = device_sn
        super().__init__(
            hass,
            _LOGGER,
            name="lumentree_yearly",
            update_interval=dt.timedelta(seconds=DEFAULT_YEARLY_INTERVAL),
        )

    async def _async_update_data(self) -> Dict[str, float]:
        try:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone()
            now = dt_util.now(timezone)
            year = now.year
            y = await self.aggregator.summarize_year(year)
            return {
                KEY_YEARLY_PV_KWH: y.get("pv", 0.0),
                KEY_YEARLY_GRID_IN_KWH: y.get("grid", 0.0),
                KEY_YEARLY_LOAD_KWH: y.get("load", 0.0),
                KEY_YEARLY_ESSENTIAL_KWH: y.get("essential", 0.0),
                KEY_YEARLY_CHARGE_KWH: y.get("charge", 0.0),
                KEY_YEARLY_DISCHARGE_KWH: y.get("discharge", 0.0),
            }
        except Exception as err:
            _LOGGER.exception("Unexpected yearly update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err


