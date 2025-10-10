"""HTTP API client for Lumentree integration."""

import asyncio
from typing import Any, Dict, Optional, List
import logging

import aiohttp
from aiohttp.client import ClientTimeout

from ..const import (
    BASE_URL,
    DEFAULT_HEADERS,
    URL_GET_SERVER_TIME,
    URL_SHARE_DEVICES,
    URL_DEVICE_MANAGE,
    URL_GET_OTHER_DAY_DATA,
    URL_GET_PV_DAY_DATA,
    URL_GET_BAT_DAY_DATA,
)
from .exceptions import ApiException, AuthException

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = ClientTimeout(total=30)
AUTH_RETRY_DELAY = 0.5
AUTH_MAX_RETRIES = 3

# Cache for device info (device info rarely changes)
_device_info_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
_cache_timeout = 3600  # 1 hour


class LumentreeHttpApiClient:
    """HTTP API client for Lumentree cloud services."""

    __slots__ = ("_session", "_token")

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the API client.

        Args:
            session: aiohttp client session for HTTP requests
        """
        self._session = session
        self._token: Optional[str] = None

    def set_token(self, token: Optional[str]) -> None:
        """Set the authentication token.

        Args:
            token: Authentication token
        """
        self._token = token
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("API token %s.", "set" if token else "cleared")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        requires_auth: bool = True,
    ) -> Dict[str, Any]:
        """Make HTTP request to API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint URL or path
            params: Query parameters
            data: Request body data
            extra_headers: Additional headers
            requires_auth: Whether authentication is required

        Returns:
            Response JSON data

        Raises:
            AuthException: If authentication fails
            ApiException: If API request fails
        """
        # Support absolute endpoint URLs
        if isinstance(endpoint, str) and (
            endpoint.startswith("http://") or endpoint.startswith("https://")
        ):
            url = endpoint
        else:
            url = f"{BASE_URL}{endpoint}"

        headers = DEFAULT_HEADERS.copy()
        if extra_headers:
            headers.update(extra_headers)

        if requires_auth:
            if self._token:
                headers["Authorization"] = self._token
            else:
                _LOGGER.error(f"Token needed for {endpoint}")
                raise AuthException("Token required")

        if data and method.upper() == "POST":
            headers["Content-Type"] = headers.get(
                "Content-Type", "application/x-www-form-urlencoded"
            )

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("HTTP %s %s", method, url)

        try:
            async with self._session.request(
                method, url, headers=headers, params=params, data=data, timeout=DEFAULT_TIMEOUT
            ) as response:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("HTTP %s response: %s", url, response.status)

                resp_text = await response.text()
                resp_text_short = resp_text[:300]

                try:
                    resp_json = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as json_err:
                    _LOGGER.error(f"Invalid JSON from {url}: {resp_text_short}")
                    raise ApiException(f"Invalid JSON: {resp_text_short}") from json_err

                if not response.ok and not resp_json:
                    response.raise_for_status()

                return_value = resp_json.get("returnValue")

                # Server time endpoint has different structure
                if endpoint == URL_GET_SERVER_TIME and "data" in resp_json:
                    return resp_json

                if return_value != 1:
                    msg = resp_json.get("msg", "Unknown")
                    _LOGGER.error(f"API error {url}: code={return_value}, msg='{msg}'")

                    if return_value == 203 or response.status in [401, 403]:
                        raise AuthException(
                            f"Auth failed (code={return_value}, status={response.status}): {msg}"
                        )

                    raise ApiException(f"API error: {msg} (code={return_value})")

                return resp_json

        except asyncio.TimeoutError as exc:
            _LOGGER.error(f"Timeout {url}")
            raise ApiException("Request timeout") from exc
        except aiohttp.ClientResponseError as exc:
            if exc.status in [401, 403]:
                raise AuthException(f"Auth error ({exc.status}): {exc.message}") from exc
            _LOGGER.error(f"HTTP error {url}: {exc.status}")
            raise ApiException(f"HTTP error: {exc.status}") from exc
        except aiohttp.ClientError as exc:
            _LOGGER.error(f"Client error {url}: {exc}")
            raise ApiException(f"Client error: {exc}") from exc
        except (AuthException, ApiException):
            raise
        except Exception as exc:
            _LOGGER.exception(f"Unexpected HTTP error {url}")
            raise ApiException(f"Unexpected error: {exc}") from exc

    async def _get_server_time(self) -> Optional[int]:
        """Get server time from API.

        Returns:
            Server timestamp or None if failed
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching server time...")

        try:
            resp = await self._request("GET", URL_GET_SERVER_TIME, requires_auth=False)
            server_time = resp.get("data", {}).get("serverTime")
            return int(server_time) if server_time else None
        except Exception as exc:
            _LOGGER.exception(f"Failed to get server time: {exc}")
            return None

    async def _get_token(self, device_id: str, server_time: int) -> Optional[str]:
        """Request authentication token.

        Args:
            device_id: Device ID for authentication
            server_time: Server timestamp

        Returns:
            Authentication token or None if failed
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Requesting token for device %s", device_id)

        try:
            payload = {"deviceIds": device_id, "serverTime": str(server_time)}
            headers = {"source": "2", "Content-Type": "application/x-www-form-urlencoded"}
            resp = await self._request(
                "POST", URL_SHARE_DEVICES, data=payload, extra_headers=headers, requires_auth=False
            )
            token = resp.get("data", {}).get("token")
            return token if token else None
        except Exception as exc:
            _LOGGER.exception(f"Failed to get token: {exc}")
            return None

    async def authenticate_device(self, device_id: str) -> str:
        """Authenticate device and get token.

        Args:
            device_id: Device ID to authenticate

        Returns:
            Authentication token

        Raises:
            AuthException: If authentication fails
        """
        _LOGGER.info(f"Authenticating device {device_id}")
        last_exc: Optional[Exception] = None

        for attempt in range(AUTH_MAX_RETRIES):
            try:
                server_time = await self._get_server_time()
                if not server_time:
                    raise ApiException("Failed to get server time")

                token = await self._get_token(device_id, server_time)
                if not token:
                    raise AuthException(f"Failed to get token (attempt {attempt + 1})")

                _LOGGER.info(f"Authentication successful for {device_id}")
                self.set_token(token)
                return token

            except (ApiException, AuthException) as exc:
                _LOGGER.warning(f"Auth attempt {attempt + 1} failed: {exc}")
                last_exc = exc
            except Exception as exc:
                _LOGGER.exception(f"Unexpected auth error (attempt {attempt + 1})")
                last_exc = AuthException(f"Unexpected error: {exc}")

            # Sleep between retries (except last attempt)
            if attempt < AUTH_MAX_RETRIES - 1:
                await asyncio.sleep(AUTH_RETRY_DELAY)

        _LOGGER.error(f"Authentication failed after {AUTH_MAX_RETRIES} attempts")
        if last_exc:
            raise last_exc
        raise AuthException("Authentication failed (unknown reason)")

    async def get_device_info(self, device_id: str) -> Dict[str, Any]:
        """Get device information with caching.

        Args:
            device_id: Device ID to query

        Returns:
            Device information dictionary
        """
        if not device_id:
            _LOGGER.warning("Device ID missing")
            return {"_error": "Device ID missing"}

        # Check cache
        import time

        current_time = time.time()

        if device_id in _device_info_cache:
            cached_data, cache_time = _device_info_cache[device_id]
            if current_time - cache_time < _cache_timeout:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Using cached device info for %s", device_id)
                return cached_data

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching device info for %s", device_id)

        try:
            params = {"page": "1", "snName": device_id}
            response_json = await self._request("POST", URL_DEVICE_MANAGE, params=params, requires_auth=True)
            response_data = response_json.get("data", {})
            devices_list = response_data.get("devices") if isinstance(response_data, dict) else None

            if isinstance(devices_list, list) and len(devices_list) > 0:
                device_info_dict = devices_list[0]
                if isinstance(device_info_dict, dict):
                    if _LOGGER.isEnabledFor(logging.DEBUG):
                        _LOGGER.debug("Device info fetched: %s", device_info_dict)

                    _LOGGER.info(
                        f"Device info: ID={device_info_dict.get('deviceId')}, "
                        f"Type={device_info_dict.get('deviceType')}, "
                        f"Controller={device_info_dict.get('controllerVersion')}"
                    )

                    # Cache result
                    _device_info_cache[device_id] = (device_info_dict, current_time)

                    return device_info_dict
                else:
                    _LOGGER.warning(f"Invalid device info format: {device_info_dict}")
                    return {"_error": "Invalid data format"}
            else:
                _LOGGER.warning(f"Device not found or empty list: {device_id}")
                return {"_error": "Device not found"}

        except (ApiException, AuthException) as exc:
            _LOGGER.error(f"Failed to get device info for {device_id}: {exc}")
            raise
        except Exception as exc:
            _LOGGER.exception(f"Unexpected error getting device info for {device_id}")
            return {"_error": f"Unexpected error: {exc}"}

    async def get_daily_stats(self, device_identifier: str, query_date: str) -> Dict[str, Optional[float]]:
        """Get daily statistics with concurrent API calls.

        Args:
            device_identifier: Device ID or serial number
            query_date: Date in YYYY-MM-DD format

        Returns:
            Dictionary with daily statistics
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching daily stats for %s @ %s", device_identifier, query_date)

        base_params = {"deviceId": device_identifier, "queryDate": query_date}

        # Call 3 APIs concurrently for 3x speed improvement
        pv_task = self._fetch_pv_data(base_params)
        bat_task = self._fetch_battery_data(base_params)
        other_task = self._fetch_other_data(base_params)

        # Wait for all to complete
        results = await asyncio.gather(pv_task, bat_task, other_task, return_exceptions=True)

        # Merge results
        return self._merge_stats_results(results)

    async def _fetch_pv_data(self, base_params: Dict[str, str]) -> Dict[str, Optional[float]]:
        """Fetch PV generation data.

        Args:
            base_params: Base query parameters

        Returns:
            PV data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_PV_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data", {})
            pv_data = data.get("pv", {})
            val = pv_data.get("tableValue")
            return {"pv_today": float(val) / 10.0 if val is not None else None}
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed PV stats ({type(exc).__name__}): {exc}")
            return {"pv_today": None}
        except Exception:
            _LOGGER.exception("Unexpected PV stats error")
            return {"pv_today": None}

    async def _fetch_battery_data(self, base_params: Dict[str, str]) -> Dict[str, Optional[float]]:
        """Fetch battery charge/discharge data.

        Args:
            base_params: Base query parameters

        Returns:
            Battery data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_BAT_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data", {})
            bats_data = data.get("bats", [])

            result = {"charge_today": None, "discharge_today": None}

            if isinstance(bats_data, list):
                if len(bats_data) > 0 and "tableValue" in bats_data[0]:
                    result["charge_today"] = float(bats_data[0]["tableValue"]) / 10.0
                if len(bats_data) > 1 and "tableValue" in bats_data[1]:
                    result["discharge_today"] = float(bats_data[1]["tableValue"]) / 10.0

            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed battery stats ({type(exc).__name__}): {exc}")
            return {"charge_today": None, "discharge_today": None}
        except Exception:
            _LOGGER.exception("Unexpected battery stats error")
            return {"charge_today": None, "discharge_today": None}

    async def _fetch_other_data(self, base_params: Dict[str, str]) -> Dict[str, Optional[float]]:
        """Fetch grid and load data.

        Args:
            base_params: Base query parameters

        Returns:
            Grid and load data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_OTHER_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data", {})

            result = {"grid_in_today": None, "load_today": None}

            # Process grid data
            grid_data = data.get("grid", {})
            grid_val = grid_data.get("tableValue")
            if grid_val is not None:
                result["grid_in_today"] = float(grid_val) / 10.0

            # Process load data
            load_data = data.get("homeload", {})
            load_val = load_data.get("tableValue")
            if load_val is not None:
                result["load_today"] = float(load_val) / 10.0

            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed other stats ({type(exc).__name__}): {exc}")
            return {"grid_in_today": None, "load_today": None}
        except Exception:
            _LOGGER.exception("Unexpected other stats error")
            return {"grid_in_today": None, "load_today": None}

    def _merge_stats_results(self, results: List[Any]) -> Dict[str, Optional[float]]:
        """Merge results from concurrent API calls.

        Args:
            results: List of results from gather()

        Returns:
            Merged statistics dictionary
        """
        merged: Dict[str, Optional[float]] = {}

        for result in results:
            if isinstance(result, dict):
                merged.update(result)
            elif isinstance(result, Exception):
                _LOGGER.warning(f"API call failed: {result}")

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Merged daily stats: %s", merged)

        return {k: v for k, v in merged.items() if v is not None}

