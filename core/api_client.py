"""HTTP API client for Lumentree integration."""

import asyncio
from typing import Any, Dict, Optional, List
import logging

import aiohttp
from aiohttp.client import ClientTimeout
from aiohttp import ClientConnectorError, ServerConnectionError

from ..const import (
    BASE_URL,
    DEFAULT_HEADERS,
    URL_GET_SERVER_TIME,
    URL_SHARE_DEVICES,
    URL_DEVICE_MANAGE,
    URL_GET_OTHER_DAY_DATA,
    URL_GET_PV_DAY_DATA,
    URL_GET_BAT_DAY_DATA,
    URL_GET_YEAR_DATA,
    URL_GET_MONTH_DATA,
)
from .exceptions import ApiException, AuthException

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = ClientTimeout(total=30)
AUTH_RETRY_DELAY = 0.5
AUTH_MAX_RETRIES = 3

# Retry configuration for API requests
API_MAX_RETRIES = 3
API_RETRY_BASE_DELAY = 1.0  # Start with 1 second
API_RETRY_MAX_DELAY = 10.0  # Cap at 10 seconds

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

    # ---------------------------
    # Helpers for statistics
    # ---------------------------

    @staticmethod
    def _to_float_list(vals: Any) -> List[float]:
        if isinstance(vals, list):
            out: List[float] = []
            for v in vals:
                try:
                    out.append(float(v))
                except Exception:
                    # Skip invalid entries
                    continue
            return out
        return []

    @staticmethod
    def _series_5min_kwh(series_w: List[float]) -> List[float]:
        # Convert W (5‑minute interval) → kWh for each step - keep full precision
        factor = (5.0 / 60.0) / 1000.0
        return [w * factor for w in series_w]

    @staticmethod
    def _series_hour_kwh(series_kwh5: List[float]) -> List[float]:
        # 12 steps of 5‑min per hour
        if not series_kwh5:
            return []
        hours = []
        for h in range(24):
            start = h * 12
            end = start + 12
            if start >= len(series_kwh5):
                hours.append(0.0)
            else:
                hours.append(sum(series_kwh5[start:end]))  # Keep full precision
        return hours

    @staticmethod
    def _sum(series: List[float]) -> float:
        # Keep full precision
        return sum(series) if series else 0.0

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
        max_retries: int = API_MAX_RETRIES,
    ) -> Dict[str, Any]:
        """Make HTTP request to API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint URL or path
            params: Query parameters
            data: Request body data
            extra_headers: Additional headers
            requires_auth: Whether authentication is required
            max_retries: Maximum number of retry attempts for network/server errors

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

        last_exc = None
        delay = API_RETRY_BASE_DELAY

        for attempt in range(max_retries):
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

                    # Success - reset delay for next request
                    delay = API_RETRY_BASE_DELAY
                    return resp_json

            except (AuthException, ApiException):
                # Don't retry auth or API errors (except network issues)
                raise
            except (asyncio.TimeoutError, ClientConnectorError, ServerConnectionError) as exc:
                # Network/connection errors - retry with exponential backoff
                last_exc = exc
                error_type = type(exc).__name__
                
                if attempt < max_retries - 1:
                    _LOGGER.warning(
                        f"Network error {url} (attempt {attempt + 1}/{max_retries}): {error_type}: {exc}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, API_RETRY_MAX_DELAY)  # Exponential backoff
                else:
                    _LOGGER.error(
                        f"Network error {url} after {max_retries} attempts: {error_type}: {exc}"
                    )
            except aiohttp.ClientResponseError as exc:
                # HTTP status errors - don't retry except for server errors (5xx)
                if exc.status in [401, 403]:
                    raise AuthException(f"Auth error ({exc.status}): {exc.message}") from exc
                
                # Retry on 5xx server errors
                if 500 <= exc.status < 600 and attempt < max_retries - 1:
                    _LOGGER.warning(
                        f"Server error {url}: {exc.status} (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {delay:.1f}s..."
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, API_RETRY_MAX_DELAY)
                else:
                    _LOGGER.error(f"HTTP error {url}: {exc.status}")
                    raise ApiException(f"HTTP error: {exc.status}") from exc
            except aiohttp.ClientError as exc:
                # Other client errors - retry
                last_exc = exc
                if attempt < max_retries - 1:
                    _LOGGER.warning(
                        f"Client error {url} (attempt {attempt + 1}/{max_retries}): {exc}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, API_RETRY_MAX_DELAY)
                else:
                    _LOGGER.error(f"Client error {url} after {max_retries} attempts: {exc}")
            except Exception as exc:
                # Unexpected errors - log but don't retry
                _LOGGER.exception(f"Unexpected HTTP error {url}")
                raise ApiException(f"Unexpected error: {exc}") from exc

        # All retries exhausted
        if last_exc:
            if isinstance(last_exc, (ClientConnectorError, ServerConnectionError)):
                raise ApiException(
                    f"Connection failed after {max_retries} attempts: Server may be down or network unavailable"
                ) from last_exc
            elif isinstance(last_exc, asyncio.TimeoutError):
                raise ApiException(
                    f"Request timeout after {max_retries} attempts: Server may be slow or unreachable"
                ) from last_exc
            else:
                raise ApiException(
                    f"Request failed after {max_retries} attempts: {last_exc}"
                ) from last_exc
        
        raise ApiException(f"Request failed after {max_retries} attempts (unknown error)")

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

        # Cleanup expired cache entries to prevent memory leak
        expired_keys = [
            key for key, (_, cache_time) in _device_info_cache.items()
            if current_time - cache_time >= _cache_timeout
        ]
        for key in expired_keys:
            _device_info_cache.pop(key, None)
        if expired_keys and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Cleaned up %d expired device info cache entries", len(expired_keys))

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

    async def get_daily_stats(self, device_identifier: str, query_date: str) -> Dict[str, Any]:
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

    async def get_year_data(self, device_identifier: str, year: int) -> Dict[str, Any]:
        """Get yearly statistics data (12 months aggregated).

        Args:
            device_identifier: Device ID or serial number
            year: Year (e.g., 2025)

        Returns:
            Dictionary with yearly data containing monthly arrays (12 values each)
            Format: {
                "pv": [12 values in 0.1 kWh],
                "grid": [12 values in 0.1 kWh],
                "homeload": [12 values in 0.1 kWh],
                "essentialLoad": [12 values in 0.1 kWh],
                "bat": [12 values in 0.1 kWh],
                ...
            }
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching year data for %s @ %s", device_identifier, year)

        try:
            params = {"deviceId": device_identifier, "year": str(year)}
            resp = await self._request("GET", URL_GET_YEAR_DATA, params=params, requires_auth=True)
            
            # Check if response is valid
            if not resp or resp.get("returnValue") != 1:
                _LOGGER.warning(f"Invalid response from getYearData API for {device_identifier} @ {year}: {resp}")
                raise ValueError(f"API returned invalid response: {resp}")
            
            data = resp.get("data", {})
            if not data:
                _LOGGER.warning(f"Empty data from getYearData API for {device_identifier} @ {year}")
                raise ValueError("API returned empty data")
            
            # Convert tableValueInfo arrays from 0.1 kWh to kWh
            result: Dict[str, Any] = {}
            for key in ["pv", "grid", "homeload", "essentialLoad", "bat", "batF"]:
                if key in data:
                    item = data[key]
                    table_value_info = self._to_float_list(item.get("tableValueInfo", []))
                    # Convert from 0.1 kWh to kWh (divide by 10)
                    result[key] = [v / 10.0 for v in table_value_info] if table_value_info else [0.0] * 12
                else:
                    result[key] = [0.0] * 12
            
            return result
        except Exception as exc:
            _LOGGER.error(f"Error fetching year data for {device_identifier} @ {year}: {exc}")
            # Re-raise exception so caller knows there was an error
            raise

    async def get_month_data(self, device_identifier: str, year: int, month: int) -> Dict[str, Any]:
        """Get monthly statistics data (daily data for a month).

        Args:
            device_identifier: Device ID or serial number
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            Dictionary with monthly data containing daily arrays (up to 31 values)
            Format: {
                "pv": [31 values in 0.1 kWh],
                "grid": [31 values in 0.1 kWh],
                "homeload": [31 values in 0.1 kWh],
                "essentialLoad": [31 values in 0.1 kWh],
                "bat": [31 values in 0.1 kWh],
                ...
            }
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching month data for %s @ %s-%02d", device_identifier, year, month)

        try:
            params = {"deviceId": device_identifier, "year": str(year), "month": str(month)}
            resp = await self._request("GET", URL_GET_MONTH_DATA, params=params, requires_auth=True)
            data = resp.get("data", {})
            
            # Convert tableValueInfo arrays from 0.1 kWh to kWh
            result: Dict[str, Any] = {}
            for key in ["pv", "grid", "homeload", "essentialLoad", "bat"]:
                if key in data:
                    item = data[key]
                    table_value_info = self._to_float_list(item.get("tableValueInfo", []))
                    # Convert from 0.1 kWh to kWh (divide by 10)
                    result[key] = [v / 10.0 for v in table_value_info] if table_value_info else []
                else:
                    result[key] = []
            
            return result
        except Exception as exc:
            _LOGGER.error(f"Error fetching month data for {device_identifier} @ {year}-{month:02d}: {exc}")
            # Return empty arrays on error
            return {
                "pv": [],
                "grid": [],
                "homeload": [],
                "essentialLoad": [],
                "bat": [],
            }

    async def _fetch_pv_data(self, base_params: Dict[str, str]) -> Dict[str, Any]:
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

            result: Dict[str, Any] = {}

            val = pv_data.get("tableValue")
            result["pv_today"] = float(val) / 10.0 if val is not None else None

            # Optional series (5‑minute W)
            series_w = self._to_float_list(pv_data.get("tableValueInfo"))
            if series_w:
                series_kwh5 = self._series_5min_kwh(series_w)
                series_hour = self._series_hour_kwh(series_kwh5)
                result.update(
                    {
                        "pv_series_5min_w": series_w,
                        "pv_series_5min_kwh": series_kwh5,
                        "pv_series_hour_kwh": series_hour,
                        "pv_sum_kwh": self._sum(series_kwh5),
                    }
                )

            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed PV stats ({type(exc).__name__}): {exc}")
            return {"pv_today": None}
        except Exception:
            _LOGGER.exception("Unexpected PV stats error")
            return {"pv_today": None}

    async def _fetch_battery_data(self, base_params: Dict[str, str]) -> Dict[str, Any]:
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

            result: Dict[str, Optional[float]] = {"charge_today": None, "discharge_today": None}

            if isinstance(bats_data, list):
                if len(bats_data) > 0 and "tableValue" in bats_data[0]:
                    result["charge_today"] = float(bats_data[0]["tableValue"]) / 10.0
                if len(bats_data) > 1 and "tableValue" in bats_data[1]:
                    result["discharge_today"] = float(bats_data[1]["tableValue"]) / 10.0

            # Signed power series → split charge/discharge
            # NOTE: API actually returns REVERSED: positive = discharge, negative = charge
            # This contradicts API_PROTOCOL.md but matches actual device behavior
            # Positive (+) = Discharge (pin phát năng lượng)
            # Negative (-) = Charge (pin nhận năng lượng)
            series_w = self._to_float_list(data.get("tableValueInfo"))
            if series_w:
                # Invert signs: API positive = discharge, API negative = charge
                # For processing: Charge = negative values (invert to positive for kWh), Discharge = positive values
                # But keep original signed in battery_series_5min_w for chart (will be inverted in sensor)
                inverted_series_w = [-w for w in series_w]  # Invert: positive becomes negative (charge), negative becomes positive (discharge)
                # Charge: was negative in API, now positive after inversion
                charge_kwh5 = self._series_5min_kwh([w if w > 0 else 0.0 for w in inverted_series_w])
                # Discharge: was positive in API, now negative after inversion
                discharge_kwh5 = self._series_5min_kwh([abs(w) if w < 0 else 0.0 for w in inverted_series_w])
                # Store inverted series for sensor processing (sensor expects: positive = charge, negative = discharge)
                result.update(
                    {
                        "battery_series_5min_w": inverted_series_w,
                        "battery_charge_series_hour_kwh": self._series_hour_kwh(charge_kwh5),
                        "battery_discharge_series_hour_kwh": self._series_hour_kwh(discharge_kwh5),
                    }
                )

            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed battery stats ({type(exc).__name__}): {exc}")
            return {"charge_today": None, "discharge_today": None}
        except Exception:
            _LOGGER.exception("Unexpected battery stats error")
            return {"charge_today": None, "discharge_today": None}

    async def _fetch_other_data(self, base_params: Dict[str, str]) -> Dict[str, Any]:
        """Fetch grid and load data.

        Args:
            base_params: Base query parameters

        Returns:
            Grid and load data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_OTHER_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data", {})

            result: Dict[str, Optional[float]] = {"grid_in_today": None, "load_today": None}

            # Grid
            grid_data = data.get("grid", {})
            grid_val = grid_data.get("tableValue")
            if grid_val is not None:
                result["grid_in_today"] = float(grid_val) / 10.0
            grid_series_w = self._to_float_list(grid_data.get("tableValueInfo"))
            if grid_series_w:
                g5 = self._series_5min_kwh(grid_series_w)
                result.update({
                    "grid_series_5min_w": grid_series_w,
                    "grid_series_5min_kwh": g5,
                    "grid_series_hour_kwh": self._series_hour_kwh(g5),
                })

            # Load and Essential (read together, process together)
            load_data = data.get("homeload", {})
            essential_data = data.get("essentialLoad", {})
            
            # Extract daily totals
            load_val = load_data.get("tableValue") if load_data else None
            e_val = essential_data.get("tableValue") if isinstance(essential_data, dict) else None
            
            if load_val is not None:
                result["load_today"] = float(load_val) / 10.0
            if e_val is not None:
                result["essential_today"] = float(e_val) / 10.0
            
            # Calculate total_load_today immediately when we have both values
            load_value = result.get("load_today")
            essential_value = result.get("essential_today")
            if load_value is not None or essential_value is not None:
                total_load_value = (float(load_value or 0.0) + float(essential_value or 0.0))
                if total_load_value > 0 or (load_value is not None and essential_value is not None):
                    result["total_load_today"] = total_load_value
            
            # Extract and process series data in parallel
            load_series_w = self._to_float_list(load_data.get("tableValueInfo")) if load_data else []
            e_series_w = self._to_float_list(essential_data.get("tableValueInfo")) if isinstance(essential_data, dict) else []
            
            # Process load series
            if load_series_w:
                l5 = self._series_5min_kwh(load_series_w)
                result.update({
                    "load_series_5min_w": load_series_w,
                    "load_series_5min_kwh": l5,
                    "load_series_hour_kwh": self._series_hour_kwh(l5),
                })
            
            # Process essential series
            if e_series_w:
                e5 = self._series_5min_kwh(e_series_w)
                result.update({
                    "essential_series_5min_w": e_series_w,
                    "essential_series_5min_kwh": e5,
                    "essential_series_hour_kwh": self._series_hour_kwh(e5),
                })
            
            # Calculate total_load series immediately when we have both series
            load_w = result.get("load_series_5min_w", [])
            essential_w = result.get("essential_series_5min_w", [])
            if load_w and essential_w:
                # Handle different lengths by padding with zeros
                max_len = max(len(load_w), len(essential_w))
                load_w_padded = list(load_w) + [0.0] * (max_len - len(load_w))
                essential_w_padded = list(essential_w) + [0.0] * (max_len - len(essential_w))
                total_load_w = [float(l or 0) + float(e or 0) for l, e in zip(load_w_padded, essential_w_padded)]
                
                load_5min_kwh = result.get("load_series_5min_kwh", [])
                essential_5min_kwh = result.get("essential_series_5min_kwh", [])
                # Handle different lengths for kWh series too
                max_len_kwh = max(len(load_5min_kwh), len(essential_5min_kwh))
                load_5min_kwh_padded = list(load_5min_kwh) + [0.0] * (max_len_kwh - len(load_5min_kwh))
                essential_5min_kwh_padded = list(essential_5min_kwh) + [0.0] * (max_len_kwh - len(essential_5min_kwh))
                total_load_5min_kwh = [float(l or 0) + float(e or 0) for l, e in zip(load_5min_kwh_padded, essential_5min_kwh_padded)]
                
                result.update({
                    "total_load_series_5min_w": total_load_w,
                    "total_load_series_5min_kwh": total_load_5min_kwh,
                    "total_load_series_hour_kwh": self._series_hour_kwh(total_load_5min_kwh),
                })
                
                # If we have series but no daily total yet, calculate from series sum
                if "total_load_today" not in result and total_load_5min_kwh:
                    result["total_load_today"] = self._sum(total_load_5min_kwh)

            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed other stats ({type(exc).__name__}): {exc}")
            return {"grid_in_today": None, "load_today": None}
        except Exception:
            _LOGGER.exception("Unexpected other stats error")
            return {"grid_in_today": None, "load_today": None}

    def _merge_stats_results(self, results: List[Any]) -> Dict[str, Any]:
        """Merge results from concurrent API calls.

        Args:
            results: List of results from gather()

        Returns:
            Merged statistics dictionary (may contain float, list, or None values)
        """
        merged: Dict[str, Any] = {}

        for result in results:
            if isinstance(result, dict):
                merged.update(result)
            elif isinstance(result, Exception):
                _LOGGER.warning(f"API call failed: {result}")

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Merged daily stats: %s", merged)

        # Filter out None values but keep lists (series data) and other valid values
        # This preserves series data even if tableValue is None
        filtered = {}
        for k, v in merged.items():
            # Keep lists (series data) and non-None values, skip None scalar values
            if isinstance(v, list) or v is not None:
                filtered[k] = v
        
        return filtered

