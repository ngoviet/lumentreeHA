"""HTTP API client for Lumentree integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import Any

import aiohttp
from aiohttp import ClientConnectorError, ServerConnectionError
from aiohttp.client import ClientTimeout

from ..const import (
    BASE_URL,
    DEFAULT_HEADERS,
    URL_DEVICE_MANAGE,
    URL_GET_ALL_DAY_DATA,
    URL_GET_BAT_DAY_DATA,
    URL_GET_MONTH_DATA,
    URL_GET_OTHER_DAY_DATA,
    URL_GET_PV_DAY_DATA,
    URL_GET_SERVER_TIME,
    URL_GET_YEAR_DATA,
    URL_SHARE_DEVICES,
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


class LumentreeHttpApiClient:
    """HTTP API client for Lumentree cloud services."""

    __slots__ = ("_session", "_token", "_device_info_cache")

    _CACHE_TIMEOUT = 3600  # 1 hour

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the API client.

        Args:
            session: aiohttp client session for HTTP requests
        """
        self._session = session
        self._token: str | None = None
        self._device_info_cache: dict[str, tuple[dict[str, Any], float]] = {}

    # ---------------------------
    # Helpers for statistics
    # ---------------------------

    @staticmethod
    def _to_float_list(vals: Any) -> list[float]:
        if isinstance(vals, list):
            out: list[float] = []
            for v in vals:
                try:
                    out.append(float(v))
                except Exception:
                    # Skip invalid entries
                    continue
            return out
        return []

    @staticmethod
    def _series_5min_kwh(series_w: list[float]) -> list[float]:
        # Convert W (5‑minute interval) → kWh for each step - keep full precision
        factor = (5.0 / 60.0) / 1000.0
        return [w * factor for w in series_w]

    @staticmethod
    def _series_hour_kwh(series_kwh5: list[float]) -> list[float]:
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
    def _sum(series: list[float]) -> float:
        # Keep full precision
        return sum(series) if series else 0.0

    # ---------------------------
    # Per-metric builders
    #
    # Both the three legacy per-metric day endpoints and the combined
    # getAllDayData endpoint describe the same six metrics with the same
    # tableValue/tableValueInfo shape, so both paths go through these builders.
    # Keeping one copy of the series math is what stops the two paths from
    # quietly disagreeing after someone edits only one of them.
    # ---------------------------

    @staticmethod
    def _metric_total_kwh(metric: Any) -> float | None:
        """Return a metric's daily total in kWh, or None when absent.

        The API reports daily totals in 0.1 kWh units.
        """
        if not isinstance(metric, dict):
            return None
        val = metric.get("tableValue")
        if val is None:
            return None
        try:
            return float(val) / 10.0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _metric_series_w(metric: Any) -> list[float]:
        """Return a metric's 5-minute series in W (empty when absent)."""
        if not isinstance(metric, dict):
            return []
        return LumentreeHttpApiClient._to_float_list(metric.get("tableValueInfo"))

    @classmethod
    def _build_pv_result(cls, metric: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"pv_today": cls._metric_total_kwh(metric)}
        series_w = cls._metric_series_w(metric)
        if series_w:
            series_kwh5 = cls._series_5min_kwh(series_w)
            result.update({
                "pv_series_5min_w": series_w,
                "pv_series_5min_kwh": series_kwh5,
                "pv_series_hour_kwh": cls._series_hour_kwh(series_kwh5),
                "pv_sum_kwh": cls._sum(series_kwh5),
            })
        return result

    @classmethod
    def _build_grid_result(cls, metric: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"grid_in_today": cls._metric_total_kwh(metric)}
        series_w = cls._metric_series_w(metric)
        if series_w:
            g5 = cls._series_5min_kwh(series_w)
            result.update({
                "grid_series_5min_w": series_w,
                "grid_series_5min_kwh": g5,
                "grid_series_hour_kwh": cls._series_hour_kwh(g5),
            })
        return result

    @classmethod
    def _build_load_result(cls, load_metric: Any, essential_metric: Any) -> dict[str, Any]:
        """Build the household/essential/total-load metrics.

        The three are produced together because total load is the sum of the
        other two -- both as a daily total and as a series -- so splitting them
        across callers would only create a way for them to disagree.
        """
        result: dict[str, Any] = {}
        load_total = cls._metric_total_kwh(load_metric)
        essential_total = cls._metric_total_kwh(essential_metric)
        if load_total is not None:
            result["load_today"] = load_total
        if essential_total is not None:
            result["essential_today"] = essential_total

        if load_total is not None or essential_total is not None:
            result["total_load_today"] = float(load_total or 0.0) + float(essential_total or 0.0)

        load_series_w = cls._metric_series_w(load_metric)
        essential_series_w = cls._metric_series_w(essential_metric)

        if load_series_w:
            l5 = cls._series_5min_kwh(load_series_w)
            result.update({
                "load_series_5min_w": load_series_w,
                "load_series_5min_kwh": l5,
                "load_series_hour_kwh": cls._series_hour_kwh(l5),
            })
        if essential_series_w:
            e5 = cls._series_5min_kwh(essential_series_w)
            result.update({
                "essential_series_5min_w": essential_series_w,
                "essential_series_5min_kwh": e5,
                "essential_series_hour_kwh": cls._series_hour_kwh(e5),
            })

        if load_series_w and essential_series_w:
            # The two series can differ in length; pad rather than truncate so a
            # short series contributes zeros instead of silently dropping the
            # tail of the longer one.
            length = max(len(load_series_w), len(essential_series_w))
            load_padded = list(load_series_w) + [0.0] * (length - len(load_series_w))
            essential_padded = list(essential_series_w) + [0.0] * (length - len(essential_series_w))
            total_load_w = [float(a or 0.0) + float(b or 0.0) for a, b in zip(load_padded, essential_padded, strict=False)]

            load_kwh5 = result.get("load_series_5min_kwh", [])
            essential_kwh5 = result.get("essential_series_5min_kwh", [])
            kwh_length = max(len(load_kwh5), len(essential_kwh5))
            load_kwh_padded = list(load_kwh5) + [0.0] * (kwh_length - len(load_kwh5))
            essential_kwh_padded = list(essential_kwh5) + [0.0] * (kwh_length - len(essential_kwh5))
            total_load_kwh5 = [float(a or 0.0) + float(b or 0.0) for a, b in zip(load_kwh_padded, essential_kwh_padded, strict=False)]

            result.update({
                "total_load_series_5min_w": total_load_w,
                "total_load_series_5min_kwh": total_load_kwh5,
                "total_load_series_hour_kwh": cls._series_hour_kwh(total_load_kwh5),
            })

            if "total_load_today" not in result:
                result["total_load_today"] = cls._sum(total_load_kwh5)

        return result

    @classmethod
    def _build_battery_result(
        cls,
        series_positive_charge: list[float],
        charge_today: float | None,
        discharge_today: float | None,
    ) -> dict[str, Any]:
        """Build battery metrics from a series where positive means charge.

        The two day endpoints disagree on representation, so each converts to
        this one convention first:
          * getBatDayData ships a single *signed* series with positive meaning
            discharge, which the caller negates before calling in.
          * getAllDayData ships separate unsigned `bat` (charge) and `batF`
            (discharge) series, which the caller subtracts.
        Downstream consumers (entities/sensor.py) expect positive = charge.
        """
        result: dict[str, Any] = {
            "charge_today": charge_today,
            "discharge_today": discharge_today,
        }
        if series_positive_charge:
            charge_kwh5 = cls._series_5min_kwh([w if w > 0 else 0.0 for w in series_positive_charge])
            discharge_kwh5 = cls._series_5min_kwh([abs(w) if w < 0 else 0.0 for w in series_positive_charge])
            result.update({
                "battery_series_5min_w": series_positive_charge,
                "battery_charge_series_hour_kwh": cls._series_hour_kwh(charge_kwh5),
                "battery_discharge_series_hour_kwh": cls._series_hour_kwh(discharge_kwh5),
            })
        return result

    def set_token(self, token: str | None) -> None:
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
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        requires_auth: bool = True,
        max_retries: int = API_MAX_RETRIES,
    ) -> dict[str, Any]:
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
            except (TimeoutError, ClientConnectorError, ServerConnectionError) as exc:
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

    async def _get_server_time(self) -> int | None:
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

    async def _get_token(self, device_id: str, server_time: int) -> str | None:
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
        last_exc: Exception | None = None

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

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
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
        current_time = time.time()

        # Cleanup expired cache entries to prevent memory leak
        expired_keys = [
            key
            for key, (_, cache_time) in self._device_info_cache.items()
            if current_time - cache_time >= self._CACHE_TIMEOUT
        ]
        for key in expired_keys:
            self._device_info_cache.pop(key, None)
        if expired_keys and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Cleaned up %d expired device info cache entries", len(expired_keys))

        if device_id in self._device_info_cache:
            cached_data, cache_time = self._device_info_cache[device_id]
            if current_time - cache_time < self._CACHE_TIMEOUT:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Using cached device info for %s", device_id)
                return cached_data

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching device info for %s", device_id)

        try:
            params = {"page": "1", "snName": device_id}
            response_json = await self._request(
                "POST", URL_DEVICE_MANAGE, params=params, requires_auth=True
            )
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
                    self._device_info_cache[device_id] = (device_info_dict, current_time)

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

    async def get_daily_stats(self, device_identifier: str, query_date: str) -> dict[str, Any]:
        """Get daily statistics, preferring the single combined endpoint.

        Tries GET /lesvr/getAllDayData first: one request instead of three, and
        one round of server-side work instead of three. Falls back to the three
        per-metric legacy endpoints when that returns nothing usable -- they
        were the only path for a long time and still answer identically, so a
        failure of the combined endpoint degrades speed rather than function.

        Args:
            device_identifier: Device ID or serial number
            query_date: Date in YYYY-MM-DD format

        Returns:
            Dictionary with daily statistics
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching daily stats for %s @ %s", device_identifier, query_date)

        combined = await self.get_all_day_data(device_identifier, query_date)
        if combined:
            return combined

        _LOGGER.info(
            "Combined day endpoint returned no data for %s @ %s; "
            "falling back to the three per-metric endpoints",
            device_identifier, query_date,
        )

        base_params = {"deviceId": device_identifier, "queryDate": query_date}

        # Call 3 APIs concurrently
        pv_task = self._fetch_pv_data(base_params)
        bat_task = self._fetch_battery_data(base_params)
        other_task = self._fetch_other_data(base_params)

        # Wait for all to complete
        results = await asyncio.gather(pv_task, bat_task, other_task, return_exceptions=True)

        # Merge results
        return self._merge_stats_results(results)


    async def get_year_data(self, device_identifier: str, year: int) -> dict[str, Any]:
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
                _LOGGER.warning(
                    f"Invalid response from getYearData API for {device_identifier} @ {year}: {resp}"
                )
                raise ValueError(f"API returned invalid response: {resp}")

            data = resp.get("data", {})
            if not data:
                _LOGGER.warning(f"Empty data from getYearData API for {device_identifier} @ {year}")
                raise ValueError("API returned empty data")

            # Convert tableValueInfo arrays from 0.1 kWh to kWh
            result: dict[str, Any] = {}
            for key in ["pv", "grid", "homeload", "essentialLoad", "bat", "batF"]:
                if key in data:
                    item = data[key]
                    table_value_info = self._to_float_list(item.get("tableValueInfo", []))
                    # Convert from 0.1 kWh to kWh (divide by 10)
                    result[key] = (
                        [v / 10.0 for v in table_value_info] if table_value_info else [0.0] * 12
                    )
                else:
                    result[key] = [0.0] * 12

            return result
        except Exception as exc:
            _LOGGER.error(f"Error fetching year data for {device_identifier} @ {year}: {exc}")
            # Re-raise exception so caller knows there was an error
            raise

    async def get_month_data(self, device_identifier: str, year: int, month: int) -> dict[str, Any]:
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
            result: dict[str, Any] = {}
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
            _LOGGER.error(
                f"Error fetching month data for {device_identifier} @ {year}-{month:02d}: {exc}"
            )
            # Return empty arrays on error
            return {
                "pv": [],
                "grid": [],
                "homeload": [],
                "essentialLoad": [],
                "bat": [],
            }

    async def _fetch_pv_data(self, base_params: dict[str, str]) -> dict[str, Any]:
        """Fetch PV generation data from the per-metric legacy endpoint.

        Args:
            base_params: Base query parameters

        Returns:
            PV data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_PV_DAY_DATA, params=base_params, requires_auth=True)
            return self._build_pv_result((resp.get("data") or {}).get("pv"))
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed PV stats ({type(exc).__name__}): {exc}")
            return {"pv_today": None}
        except Exception:
            _LOGGER.exception("Unexpected PV stats error")
            return {"pv_today": None}

    async def _fetch_battery_data(self, base_params: dict[str, str]) -> dict[str, Any]:
        """Fetch battery charge/discharge data from the legacy endpoint.

        Args:
            base_params: Base query parameters

        Returns:
            Battery data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_BAT_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data") or {}
            bats_data = data.get("bats", [])

            charge_today: float | None = None
            discharge_today: float | None = None
            if isinstance(bats_data, list):
                if len(bats_data) > 0 and isinstance(bats_data[0], dict) and "tableValue" in bats_data[0]:
                    charge_today = float(bats_data[0]["tableValue"]) / 10.0
                if len(bats_data) > 1 and isinstance(bats_data[1], dict) and "tableValue" in bats_data[1]:
                    discharge_today = float(bats_data[1]["tableValue"]) / 10.0

            # This endpoint's series is signed with positive meaning DISCHARGE
            # (which contradicts the old API_PROTOCOL.md; the device is the
            # authority). Negate so the shared builder sees positive = charge.
            series_w = self._to_float_list(data.get("tableValueInfo"))
            return self._build_battery_result(
                [-w for w in series_w], charge_today, discharge_today
            )
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed battery stats ({type(exc).__name__}): {exc}")
            return {"charge_today": None, "discharge_today": None}
        except Exception:
            _LOGGER.exception("Unexpected battery stats error")
            return {"charge_today": None, "discharge_today": None}

    async def _fetch_other_data(self, base_params: dict[str, str]) -> dict[str, Any]:
        """Fetch grid and load data from the legacy endpoint.

        Args:
            base_params: Base query parameters

        Returns:
            Grid and load data dictionary
        """
        try:
            resp = await self._request("GET", URL_GET_OTHER_DAY_DATA, params=base_params, requires_auth=True)
            data = resp.get("data") or {}
            result = self._build_grid_result(data.get("grid"))
            result.update(self._build_load_result(data.get("homeload"), data.get("essentialLoad")))
            return result
        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed other stats ({type(exc).__name__}): {exc}")
            return {"grid_in_today": None, "load_today": None}
        except Exception:
            _LOGGER.exception("Unexpected other stats error")
            return {"grid_in_today": None, "load_today": None}

    @classmethod
    def _merge_all_day_payload(cls, payload: Any) -> dict[str, Any]:
        """Turn a getAllDayData `data` object into the standard stats dict.

        Split out from the request method so the mapping can be tested against
        captured payloads without a live session -- the sign convention and the
        absent-`batF` case are the parts worth pinning down, and neither needs
        the network to exercise.
        """
        if not isinstance(payload, dict) or not payload:
            return {}

        data = payload
        result = cls._build_pv_result(data.get("pv"))
        result.update(cls._build_grid_result(data.get("grid")))
        result.update(cls._build_load_result(data.get("homeload"), data.get("essentialLoad")))

        charge_series = cls._metric_series_w(data.get("bat"))
        discharge_series = cls._metric_series_w(data.get("batF"))
        # Two unsigned series -> one signed series, positive meaning charge.
        # Pad rather than truncate: a missing or short discharge series is the
        # normal case (no discharge omits batF entirely rather than zero-filling
        # it), and truncating would silently drop the charge series' tail.
        length = max(len(charge_series), len(discharge_series))
        charge_padded = list(charge_series) + [0.0] * (length - len(charge_series))
        discharge_padded = list(discharge_series) + [0.0] * (length - len(discharge_series))
        signed_series = [c - d for c, d in zip(charge_padded, discharge_padded, strict=False)]

        charge_today = cls._metric_total_kwh(data.get("bat"))
        discharge_today = cls._metric_total_kwh(data.get("batF"))
        # The combined endpoint omits batF when the day had no discharge, where
        # the legacy endpoint it replaces returned an explicit zero. Left as
        # None that difference would leak to callers as `unknown` instead of
        # `0 kWh`, so the two sources would not actually be interchangeable.
        # A battery that reported charge is a battery that was present, so a
        # missing batF alongside a present bat means "no discharge", not
        # "no data".
        if charge_today is not None and discharge_today is None:
            discharge_today = 0.0

        result.update(cls._build_battery_result(signed_series, charge_today, discharge_today))
        return result

    async def get_all_day_data(self, device_identifier: str, query_date: str) -> dict[str, Any]:
        """Fetch a whole day's statistics in one request.

        Replaces three concurrent calls (PV, battery, grid/load) with one. The
        response carries every metric under `data`, plus a `titleParams` array
        describing them.

        Two representation differences from the legacy endpoints, both handled
        in `_merge_all_day_payload` rather than at the call site:

        * Battery arrives as two *unsigned* series -- `bat` (charge) and `batF`
          (discharge) -- where the legacy endpoint used one signed series.
        * `batF` is **omitted entirely** when the day had no discharge, rather
          than being present and zero.

        Args:
            device_identifier: Device ID or serial number
            query_date: Date in YYYY-MM-DD format

        Returns:
            Dictionary with the same keys the legacy three-call path produces,
            so callers cannot tell which endpoint served them.
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching all-day data for %s @ %s", device_identifier, query_date)

        try:
            resp = await self._request(
                "GET",
                URL_GET_ALL_DAY_DATA,
                params={"deviceId": device_identifier, "queryDate": query_date},
                requires_auth=True,
            )
            return self._merge_all_day_payload(resp.get("data"))

        except (ApiException, AuthException) as exc:
            _LOGGER.warning(f"Failed all-day stats ({type(exc).__name__}): {exc}")
            return {}
        except Exception:
            _LOGGER.exception("Unexpected all-day stats error")
            return {}


    def _merge_stats_results(self, results: Iterable[Any]) -> dict[str, Any]:
        """Merge results from concurrent API calls.

        Args:
            results: List of results from gather()

        Returns:
            Merged statistics dictionary (may contain float, list, or None values)
        """
        merged: dict[str, Any] = {}

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
