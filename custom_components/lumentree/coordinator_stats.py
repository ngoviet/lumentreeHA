# /config/custom_components/lumentree/coordinator_stats.py
# Final corrected version with fixed fallback syntax and timezone logic

import asyncio
import datetime
from typing import Any, Dict, Optional
import logging

from homeassistant.core import HomeAssistant
# Import UpdateFailed and DataUpdateCoordinator from correct module
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
# Import datetime and timezone utility functions
from homeassistant.util import dt as dt_util
# Import ConfigEntryAuthFailed from correct module
from homeassistant.exceptions import ConfigEntryAuthFailed

try:
    # Import required components from component
    from .api import LumentreeHttpApiClient, ApiException, AuthException
    from .const import DOMAIN, _LOGGER, DEFAULT_STATS_INTERVAL, CONF_DEVICE_SN
except ImportError as import_err:
    # --- Fallback Definitions (Fixed syntax errors) ---
    _LOGGER = logging.getLogger(__name__)
    _LOGGER.error(f"ImportError in coordinator_stats: {import_err}. Using fallback definitions.")
    DOMAIN = "lumentree"
    DEFAULT_STATS_INTERVAL = 1800
    CONF_DEVICE_SN = "device_sn"

    # Fallback Class API (Fixed syntax errors)
    class LumentreeHttpApiClient:
        def __init__(self, session=None):
            pass
        # Define async def correctly (indented)
        async def get_daily_stats(self, sn, date):
            _LOGGER.warning("Using fallback get_daily_stats - returning empty dict.")
            return {}

    # Fallback for Exceptions (Separate lines)
    class ApiException(Exception):
        pass
    class AuthException(ApiException):
        pass

    try:
        from homeassistant.helpers.update_coordinator import UpdateFailed
    # Separate except and fallback class to different lines
    except ImportError:
        class UpdateFailed(Exception):
            pass
    try:
        from homeassistant.exceptions import ConfigEntryAuthFailed
    # Separate except and fallback class to different lines
    except ImportError:
        class ConfigEntryAuthFailed(Exception):
            pass
    # --- End of Fallback section ---

# --- Coordinator Class Definition ---
class LumentreeStatsCoordinator(DataUpdateCoordinator[Dict[str, Optional[float]]]):
    """Coordinator to fetch daily statistics via HTTP API."""

    def __init__(self, hass: HomeAssistant, api_client: LumentreeHttpApiClient, device_sn: str):
        """Initialize the coordinator."""
        self.api_client = api_client
        self.device_sn = device_sn
        update_interval = datetime.timedelta(seconds=DEFAULT_STATS_INTERVAL)

        # Call super().__init__
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_stats_{device_sn}", # Name for debugging
            update_interval=update_interval,
        )
        _LOGGER.info(
            f"Initialized Stats Coordinator for {device_sn} with interval: {update_interval}"
        )

    async def _async_update_data(self) -> Dict[str, Optional[float]]:
        """Fetch data from the HTTP API endpoint."""
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching daily stats via HTTP for %s", self.device_sn)
        try:
            # Get timezone and current date (Fixed TypeError)
            timezone = None
            try:
                tz_string = self.hass.config.time_zone
                if tz_string:
                    timezone = dt_util.get_time_zone(tz_string)
                    if not timezone:
                        _LOGGER.warning(f"Could not get timezone object for '{tz_string}', using default.")
                        timezone = dt_util.get_default_time_zone()
                else:
                    _LOGGER.warning("Timezone not configured in HA, using default.")
                    timezone = dt_util.get_default_time_zone()
            except Exception as tz_err:
                 _LOGGER.error(f"Error getting timezone from HA config: {tz_err}. Using default.")
                 timezone = dt_util.get_default_time_zone()

            today_str = dt_util.now(timezone).strftime("%Y-%m-%d")
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Querying daily stats for date: %s", today_str)

            # Call API
            async with asyncio.timeout(60):
                stats_data = await self.api_client.get_daily_stats(self.device_sn, today_str)

            # Process results
            if stats_data is None:
                 _LOGGER.warning(f"API client returned None stats data for {self.device_sn} on {today_str}")
                 raise UpdateFailed("API client failed to return stats data")
            if not isinstance(stats_data, dict):
                _LOGGER.error(f"API client returned unexpected data type for stats: {type(stats_data)}")
                raise UpdateFailed("Invalid data type received from API")

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Successfully fetched daily stats: %s", stats_data)
            return stats_data

        # Handle errors
        except AuthException as err:
            _LOGGER.error(f"Authentication error fetching stats: {err}. Please reconfigure integration.")
            raise ConfigEntryAuthFailed(f"Authentication error: {err}") from err
        except ApiException as err:
            _LOGGER.error(f"API error fetching stats: {err}")
            raise UpdateFailed(f"API error: {err}") from err
        except asyncio.TimeoutError as err:
            _LOGGER.error(f"Timeout fetching stats for {self.device_sn}")
            raise UpdateFailed("Timeout fetching statistics data") from err
        except Exception as err:
            _LOGGER.exception(f"Unexpected error fetching stats data")
            raise UpdateFailed(f"Unexpected error: {err}") from err