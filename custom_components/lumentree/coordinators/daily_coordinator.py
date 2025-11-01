"""Daily coordinator for fetching today's HTTP stats (every 10 minutes)."""

from __future__ import annotations

import datetime as dt
import asyncio
import logging
from typing import Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..core.api_client import LumentreeHttpApiClient
from ..core.exceptions import ApiException, AuthException
from ..const import DEFAULT_DAILY_INTERVAL


_LOGGER = logging.getLogger(__name__)


class DailyStatsCoordinator(DataUpdateCoordinator[Dict[str, Optional[float]]]):
    def __init__(self, hass: HomeAssistant, api: LumentreeHttpApiClient, device_sn: str, interval_sec: int | None = None) -> None:
        self.api = api
        self.device_sn = device_sn

        super().__init__(
            hass,
            _LOGGER,
            name=f"lumentree_daily_{device_sn}",
            update_interval=dt.timedelta(seconds=(interval_sec or DEFAULT_DAILY_INTERVAL)),
        )

    async def _async_update_data(self) -> Dict[str, Optional[float]]:
        try:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.get_default_time_zone()
            today_str = dt_util.now(timezone).strftime("%Y-%m-%d")
            async with asyncio.timeout(60):
                return await self.api.get_daily_stats(self.device_sn, today_str)
        except AuthException as err:
            raise UpdateFailed(f"Auth error: {err}") from err
        except ApiException as err:
            raise UpdateFailed(f"API error: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout fetching daily data") from err
        except Exception as err:
            _LOGGER.exception("Unexpected daily update error")
            raise UpdateFailed(f"Unexpected error: {err}") from err


