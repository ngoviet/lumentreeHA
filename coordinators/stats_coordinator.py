"""Statistics coordinator for Lumentree integration."""

import asyncio
import datetime
from typing import Any, Dict, Optional
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import ConfigEntryAuthFailed

from ..core.api_client import LumentreeHttpApiClient
from ..core.exceptions import ApiException, AuthException
from ..const import DOMAIN, DEFAULT_STATS_INTERVAL, CONF_DEVICE_SN

_LOGGER = logging.getLogger(__name__)


class LumentreeStatsCoordinator(DataUpdateCoordinator[Dict[str, Optional[float]]]):
    """Coordinator to fetch daily statistics via HTTP API."""

    __slots__ = ("api_client", "device_sn")

    def __init__(
        self, hass: HomeAssistant, api_client: LumentreeHttpApiClient, device_sn: str
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            api_client: API client for HTTP requests
            device_sn: Device serial number
        """
        self.api_client = api_client
        self.device_sn = device_sn
        update_interval = datetime.timedelta(seconds=DEFAULT_STATS_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_stats_{device_sn}",
            update_interval=update_interval,
        )

        _LOGGER.info(
            f"Initialized stats coordinator for {device_sn} with interval: {update_interval}"
        )

    async def _async_update_data(self) -> Dict[str, Optional[float]]:
        """Fetch data from the HTTP API endpoint.

        Returns:
            Dictionary with daily statistics

        Raises:
            ConfigEntryAuthFailed: If authentication fails
            UpdateFailed: If data fetching fails
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching daily stats for %s", self.device_sn)

        try:
            # Get timezone and current date
            timezone = None
            try:
                tz_string = self.hass.config.time_zone
                if tz_string:
                    timezone = dt_util.get_time_zone(tz_string)
                    if not timezone:
                        _LOGGER.warning(
                            f"Could not get timezone object for '{tz_string}', using default"
                        )
                        timezone = dt_util.get_default_time_zone()
                else:
                    _LOGGER.warning("Timezone not configured, using default")
                    timezone = dt_util.get_default_time_zone()
            except Exception as tz_err:
                _LOGGER.error(f"Error getting timezone: {tz_err}. Using default")
                timezone = dt_util.get_default_time_zone()

            today_str = dt_util.now(timezone).strftime("%Y-%m-%d")
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Querying daily stats for date: %s", today_str)

            # Call API with timeout
            async with asyncio.timeout(60):
                stats_data = await self.api_client.get_daily_stats(
                    self.device_sn, today_str
                )

            # Process results
            if stats_data is None:
                _LOGGER.warning(
                    f"API client returned None for {self.device_sn} on {today_str}"
                )
                raise UpdateFailed("API client failed to return stats data")

            if not isinstance(stats_data, dict):
                _LOGGER.error(
                    f"API client returned unexpected type: {type(stats_data)}"
                )
                raise UpdateFailed("Invalid data type from API")

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Successfully fetched daily stats: %s", stats_data)

            return stats_data

        except AuthException as err:
            _LOGGER.error(
                f"Authentication error fetching stats: {err}. Reconfiguration required"
            )
            raise ConfigEntryAuthFailed(f"Authentication error: {err}") from err
        except ApiException as err:
            _LOGGER.error(f"API error fetching stats: {err}")
            raise UpdateFailed(f"API error: {err}") from err
        except asyncio.TimeoutError as err:
            _LOGGER.error(f"Timeout fetching stats for {self.device_sn}")
            raise UpdateFailed("Timeout fetching statistics data") from err
        except Exception as err:
            _LOGGER.exception(f"Unexpected error fetching stats")
            raise UpdateFailed(f"Unexpected error: {err}") from err

