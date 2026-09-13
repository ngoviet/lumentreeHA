"""HTTP API client for Lumentree integration."""

from __future__ import annotations

import asyncio
import logging
import math
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

# The vendor's catch-all "this endpoint does not exist" answer.  It is a
# property of the host, so it is worth remembering; see
# `_all_day_data_absent` and docs/api/API_ENDPOINTS_DISCOVERED.md.
RETURN_VALUE_ENDPOINT_MISSING = 998


def _finite_or_none(value: Any) -> float | None:
    """Coerce a vendor number, treating an unusable one as absent.

    ``float()`` succeeds on the bare ``NaN``/``Infinity`` literals that
    ``json.loads`` accepts, so a malformed or truncated vendor body produces a
    non-finite number without raising.  A non-finite reading is no more usable
    than an unparsable one, and letting it through is worse: it survives
    ``_drop_none_scalars`` (NaN is not None), survives the coordinator's
    ``or 0.0`` (NaN is truthy) and survives an all-zero emptiness check (NaN
    compares False), so it reaches the year cache and is summed into every
    aggregate derived from that year.  Absent is the only answer downstream
    already knows how to handle.

    ``OverflowError`` is caught alongside them because ``json.loads`` produces
    an arbitrary-precision ``int`` for an integer literal of any magnitude, and
    ``float()`` refuses the ones that do not fit a double.  It is an
    ``ArithmeticError``, not a ``ValueError``, so listing it is not optional --
    without it one oversized literal in a body raises out of every caller.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


class LumentreeHttpApiClient:
    """HTTP API client for Lumentree cloud services."""

    __slots__ = ("_session", "_token", "_device_info_cache", "_all_day_data_absent")

    _CACHE_TIMEOUT = 3600  # 1 hour

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the API client.

        Args:
            session: aiohttp client session for HTTP requests
        """
        self._session = session
        self._token: str | None = None
        self._device_info_cache: dict[str, tuple[dict[str, Any], float]] = {}
        # Set once the host has answered 998 for the combined day endpoint.
        # 998 means "endpoint does not exist", which is a property of the host,
        # not of the device or the day, so it holds for the client's lifetime.
        self._all_day_data_absent = False

    # ---------------------------
    # Helpers for statistics
    # ---------------------------

    @staticmethod
    def _to_float_list(vals: Any) -> list[float]:
        if isinstance(vals, list):
            out: list[float] = []
            for v in vals:
                number = _finite_or_none(v)
                if number is not None:
                    out.append(number)
            return out
        return []

    @staticmethod
    def _series_5min_kwh(series_w: list[tuple[int, float]]) -> list[tuple[int, float]]:
        # Convert W (5‑minute interval) → kWh for each step - keep full precision
        factor = (5.0 / 60.0) / 1000.0
        return [(slot, w * factor) for slot, w in series_w]

    @staticmethod
    def _series_hour_kwh(series_kwh5: list[tuple[int, float]]) -> list[float]:
        """Fold a 5-minute kWh frame into 24 hourly sums.

        The hour comes from the slot, not from the array index.  That is the
        whole reason this helper takes a frame: a series with a hole in it
        keeps every later sample in the hour it was reported for, and a day
        that stopped early leaves the remaining hours at zero instead of
        pulling the readings it did send backwards.  Bucketing the flat list
        by index did exactly that damage, and did it silently.
        """
        if not series_kwh5:
            return []
        hours = [0.0] * 24
        for slot, value in series_kwh5:
            hour = slot // 12  # 12 steps of 5 minutes per hour
            if 0 <= hour < 24:
                hours[hour] += value  # Keep full precision
        return hours

    @staticmethod
    def _values(frame: list[tuple[int, float]]) -> list[float]:
        """A frame's readings in slot order -- the flat lists consumers read."""
        return [value for _, value in frame]

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
        number = _finite_or_none(val)
        return None if number is None else number / 10.0

    @staticmethod
    def _slot_readings(metric: Any) -> list[tuple[int, float]]:
        """A metric's reported 5-minute readings, each keyed by its slot.

        This is the identity a series has to keep: a sample's hour is derived
        from the slot it was reported for, so an unreadable entry at slot n
        must not pull the samples after it one slot earlier.  Only reported
        values are framed; a hole simply has no entry.
        """
        if not isinstance(metric, dict):
            return []
        vals = metric.get("tableValueInfo")
        if not isinstance(vals, list):
            return []
        frame: list[tuple[int, float]] = []
        for slot, value in enumerate(vals):
            number = _finite_or_none(value)
            if number is not None:
                frame.append((slot, number))
        return frame

    @staticmethod
    def _slot_sum(
        left: list[tuple[int, float]],
        right: list[tuple[int, float]],
    ) -> list[tuple[int, float]]:
        """Add two frames slot by slot.

        Used for the total-load series, where the two inputs are magnitudes
        that simply add.  A slot neither input reported contributes no entry.
        """
        a = dict(left)
        b = dict(right)
        summed: list[tuple[int, float]] = []
        for slot in range(max([*a, *b], default=-1) + 1):
            x = a.get(slot)
            y = b.get(slot)
            if x is None and y is None:
                continue
            summed.append((slot, float(x or 0.0) + float(y or 0.0)))
        return summed

    @staticmethod
    def _slot_difference(
        charge_slots: list[tuple[int, float]],
        discharge_slots: list[tuple[int, float]],
    ) -> list[tuple[int, float]]:
        """Sign the two unsigned battery frames against each other, by slot.

        Charge reported and no discharge that slot means +charge; discharge
        reported with no charge means -discharge; both reported means the
        difference.  A slot neither series reported has no entry, so a hole in
        one frame cannot book a phantom reading derived from the other.
        """
        charge = dict(charge_slots)
        discharge = dict(discharge_slots)
        signed: list[tuple[int, float]] = []
        for slot in range(max([*charge, *discharge], default=-1) + 1):
            c = charge.get(slot)
            d = discharge.get(slot)
            if c is not None and d is not None:
                signed.append((slot, c - d))
            elif d is not None:
                signed.append((slot, -d))
            elif c is not None:
                signed.append((slot, c))
        return signed

    @classmethod
    def _build_pv_result(cls, metric: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"pv_today": cls._metric_total_kwh(metric)}
        series = cls._slot_readings(metric)
        if series:
            series_kwh5 = cls._series_5min_kwh(series)
            result.update({
                "pv_series_5min_w": cls._values(series),
                "pv_series_5min_kwh": cls._values(series_kwh5),
                "pv_series_hour_kwh": cls._series_hour_kwh(series_kwh5),
                "pv_sum_kwh": cls._sum(cls._values(series_kwh5)),
            })
        return result

    @classmethod
    def _build_grid_result(cls, metric: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"grid_in_today": cls._metric_total_kwh(metric)}
        series = cls._slot_readings(metric)
        if series:
            g5 = cls._series_5min_kwh(series)
            result.update({
                "grid_series_5min_w": cls._values(series),
                "grid_series_5min_kwh": cls._values(g5),
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

        load_series = cls._slot_readings(load_metric)
        essential_series = cls._slot_readings(essential_metric)

        if load_series:
            l5 = cls._series_5min_kwh(load_series)
            result.update({
                "load_series_5min_w": cls._values(load_series),
                "load_series_5min_kwh": cls._values(l5),
                "load_series_hour_kwh": cls._series_hour_kwh(l5),
            })
        if essential_series:
            e5 = cls._series_5min_kwh(essential_series)
            result.update({
                "essential_series_5min_w": cls._values(essential_series),
                "essential_series_5min_kwh": cls._values(e5),
                "essential_series_hour_kwh": cls._series_hour_kwh(e5),
            })

        if load_series and essential_series:
            # Slots, not array positions: a short series contributes nothing to
            # the slots it never reported instead of silently adding its zeros
            # to the tail of the longer one.
            total_load = cls._slot_sum(load_series, essential_series)
            total_load_kwh5 = cls._series_5min_kwh(total_load)

            result.update({
                "total_load_series_5min_w": cls._values(total_load),
                "total_load_series_5min_kwh": cls._values(total_load_kwh5),
                "total_load_series_hour_kwh": cls._series_hour_kwh(total_load_kwh5),
            })

            if "total_load_today" not in result:
                result["total_load_today"] = cls._sum(cls._values(total_load_kwh5))

        return result

    @classmethod
    def _build_battery_result(
        cls,
        series_slots: list[tuple[int, float]],
        charge_today: float | None,
        discharge_today: float | None,
    ) -> dict[str, Any]:
        """Build battery metrics from a signed frame where positive means charge.

        The two day endpoints disagree on representation, so each produces one
        of these frames first:
          * getBatDayData ships a single *signed* series with positive meaning
            discharge, which the caller negates into this frame.
          * getAllDayData ships separate unsigned `bat` (charge) and `batF`
            (discharge) series, which the caller signs against each other.
        Downstream consumers (entities/sensor.py) expect positive = charge.
        """
        result: dict[str, Any] = {
            "charge_today": charge_today,
            "discharge_today": discharge_today,
        }
        if not series_slots:
            return result
        # The hourly rollups keep one slot each, so a short day still lands in
        # the right hours.  Both sides are published over the slots the frame
        # reported, so a day that only ever charged still carries a 24-entry
        # discharge series of zeros: "this side was idle" and "there was no
        # battery data at all" are different answers, and only the second one
        # is allowed to publish no series.
        factor = (5.0 / 60.0) / 1000.0
        charge_kwh5 = [
            (slot, value * factor if value > 0 else 0.0) for slot, value in series_slots
        ]
        discharge_kwh5 = [
            (slot, abs(value) * factor if value < 0 else 0.0) for slot, value in series_slots
        ]
        result.update({
            "battery_series_5min_w": cls._values(series_slots),
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

                        raise ApiException(
                            f"API error: {msg} (code={return_value})", code=return_value
                        )

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
        per-metric legacy endpoints when that comes back empty -- a transport
        error, or a response whose every metric was unusable -- they were the
        only path for a long time and still answer identically for PV, grid,
        load and essential load, which the recorded comparison measured equal.
        The battery discharge representation differs (an explicit zero there,
        an absent `batF` here) and the client normalises it, though the battery
        mapping itself is unverified because the captured device has no
        battery. A failure of the combined endpoint therefore degrades speed
        rather than function. An empty result means exactly that for both
        sources, so this test is the endpoint's own "no data" answer either way.

        One failure is not retried: a 998 ("endpoint does not exist") is a
        property of the host, so it is cached on the client and every later
        poll skips straight to the legacy calls. The fallback notice above
        therefore fires at most once per client rather than once per poll.

        Args:
            device_identifier: Device ID or serial number
            query_date: Date in YYYY-MM-DD format

        Returns:
            Dictionary with daily statistics
        """
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Fetching daily stats for %s @ %s", device_identifier, query_date)

        if self._all_day_data_absent:
            # A previous poll was told this host has no combined day endpoint.
            # Asking again would buy the same 998, so the retry ladder starts at
            # the legacy calls and the fallback notice below stays quiet.
            combined: dict[str, Any] = {}
        else:
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
                if len(bats_data) > 0 and isinstance(bats_data[0], dict):
                    charge_today = self._metric_total_kwh(bats_data[0])
                if len(bats_data) > 1 and isinstance(bats_data[1], dict):
                    discharge_today = self._metric_total_kwh(bats_data[1])

            # This endpoint's series is signed with positive meaning DISCHARGE
            # (which contradicts the old API_PROTOCOL.md; the device is the
            # authority). Negate so the shared builder sees positive = charge.
            series_slots = [
                (slot, -value) for slot, value in self._slot_readings(data)
            ]
            return self._build_battery_result(series_slots, charge_today, discharge_today)
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

    @staticmethod
    def _drop_none_scalars(stats: dict[str, Any]) -> dict[str, Any]:
        """Keep series data and real readings; drop metrics that came back None.

        A None scalar means the metric was reported unusable, and the two
        sources of a day's statistics both have to answer that the same way.
        """
        return {
            key: value
            for key, value in stats.items()
            if isinstance(value, list) or value is not None
        }

    @classmethod
    def _merge_all_day_payload(cls, payload: Any) -> dict[str, Any]:
        """Turn a getAllDayData `data` object into the standard stats dict.

        Returns an empty dict when the payload carried no usable metric at all,
        the same as the three per-metric endpoints do, so a caller can treat
        "empty" as "no data" regardless of which source answered.

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

        # Two unsigned series -> one signed series, positive meaning charge.
        # Signing is by slot, so an entry that cannot be read in one series
        # cannot shift the other's samples onto the wrong 5-minute step.
        signed_slots = cls._slot_difference(
            cls._slot_readings(data.get("bat")),
            cls._slot_readings(data.get("batF")),
        )

        charge_today = cls._metric_total_kwh(data.get("bat"))
        discharge_today = cls._metric_total_kwh(data.get("batF"))
        # An absent side is normalised to 0.0 kWh whenever the other side for
        # the same day is present.  The gate is the other side's presence
        # because presence is the only proxy the payload offers for "this
        # device has a battery and reported on this day": the slot-level
        # omission is an output detail the legacy endpoint never shared.
        # Symmetric on purpose -- "bat present, batF absent" and "batF present,
        # bat absent" are the same situation seen from either end, and the
        # second one would otherwise reach the same substituted zero by a
        # different road: charge_today would stay None, _drop_none_scalars
        # would drop the key, and the coordinator's `or 0.0` would read it back
        # as 0.0.  Both directions now agree in the returned dict shape and in
        # the durable outcome, so neither is an undocumented instance of the
        # other's trade.
        #
        # This is a chosen trade, not a proven equivalence -- it is what keeps
        # the combined source answering the same as getBatDayData, whose
        # absent bats[0]/bats[1] also reads back as 0 downstream.
        # Counterfactual: a day that discharged while omitting batF is reported
        # as 0 kWh rather than unknown, and no payload in this repo can rule
        # that out.
        #
        # The wrong 0 is durable and that is accepted deliberately: the
        # coordinator persists the day into the year cache on rollover, where
        # recompute_aggregates folds it into the monthly, yearly and total
        # statistics the dashboards read, and a later poll does not rewrite an
        # already-finalized day.  The alternative -- teaching the coordinator
        # and the cache to distinguish "not reported" from "measured zero" --
        # needs durable state and a cache-format decision, so it is out of
        # scope for a change whose point is one request instead of three.
        #
        # A second consequence of the same trade: the coordinator re-queries the
        # whole current day on every poll, so the published
        # `battery_series_5min_w` and both hourly rollups reflect only what the
        # response in hand carried.  Within one payload the two frames are
        # unioned by slot -- a side present at a slot keeps it, and neither can
        # drop the other -- but nothing carries a slot across polls, so a day
        # whose payload gains or loses a side between polls can publish a
        # different series on each poll.  Accepted for the same reason as the
        # durable zero: a monotonic across-poll union would need durable
        # per-day state and a cache-format decision.  Counterfactual: a day
        # where the vendor reports one side only, which no payload in this repo
        # can confirm or rule out.
        if charge_today is not None and discharge_today is None:
            discharge_today = 0.0
        elif discharge_today is not None and charge_today is None:
            charge_today = 0.0

        result.update(cls._build_battery_result(signed_slots, charge_today, discharge_today))
        return cls._drop_none_scalars(result)

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
            so callers cannot tell which endpoint served them. Empty when the
            call failed or every metric was unusable -- the same "no data"
            answer the legacy path gives, so a caller can fall back on it.
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
            if getattr(exc, "code", None) == RETURN_VALUE_ENDPOINT_MISSING:
                # The host answered "no such endpoint" for the combined day
                # endpoint.  That will not change on a later poll, so record it
                # and stop paying for the request; `get_daily_stats` reads the
                # flag and goes straight to the legacy calls.  Only this code
                # sets it -- a transport error or any other return value leaves
                # it alone, so the combined endpoint is still retried.
                self._all_day_data_absent = True
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

        return self._drop_none_scalars(merged)
