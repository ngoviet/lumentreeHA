"""Lumentree Inverter integration for Home Assistant."""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    _LOGGER,
    CONF_DEVICE_ID,
    CONF_DEVICE_SN,
    CONF_HTTP_TOKEN,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    today_in_ha,
)
from .coordinators.daily_coordinator import DailyStatsCoordinator
from .coordinators.monthly_coordinator import MonthlyStatsCoordinator
from .coordinators.total_coordinator import TotalStatsCoordinator
from .coordinators.yearly_coordinator import YearlyStatsCoordinator
from .core.api_client import ApiException, AuthException, LumentreeHttpApiClient
from .core.mqtt_client import LumentreeMqttClient
from .services import cache as cache_io
from .services.aggregator import StatsAggregator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# Set up from config entries only; there is no YAML configuration.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Delay before the monthly/yearly/total coordinators are warmed, so the backfill
# that the daily coordinator kicks off has time to fill the cache they read.
# Module-level so a test can shrink it; ten real seconds per entry otherwise
# dominates the end-to-end suite.
_STAGGER_DELAY_SECONDS = 10.0

# The nightly delta runs at this local time.  Shortly after midnight, so
# yesterday is complete on the vendor side, and not exactly on it, so it does
# not race the daily coordinator's own rollover save.
_NIGHTLY_HOUR = 0
_NIGHTLY_MINUTE = 20

# Optional field accepted by every service: restricts the call to one inverter.
# Without it a service applies to every configured inverter.
ATTR_DEVICE_SN = "device_sn"

# The entry-data key under which the per-entry runtime objects live.
_KEY_AGGREGATOR = "aggregator"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Lumentree integration.

    Services are registered here, once, rather than per config entry: a
    per-entry registration was overwritten by each later entry, so with two
    inverters every service silently acted on whichever one loaded last, and
    nothing ever unregistered them.
    """
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lumentree from a config entry."""
    _LOGGER.info("Setting up Lumentree: %s (%s)", entry.title, entry.entry_id)
    hass.data.setdefault(DOMAIN, {})
    entry_data: dict[str, Any] = {"entry": entry}
    hass.data[DOMAIN][entry.entry_id] = entry_data

    # The cache lives under the HA config directory.  It used to be a path
    # relative to the process working directory, which only coincides with the
    # config directory in the container image.
    cache_io.set_base_dir(hass.config.path(".storage", "lumentree_stats"))

    mqtt_client: LumentreeMqttClient | None = None

    try:
        device_sn = entry.data[CONF_DEVICE_SN]
        device_id = entry.data.get(CONF_DEVICE_ID, device_sn)
        http_token = entry.data.get(CONF_HTTP_TOKEN)
        entry_data["device_sn"] = device_sn
        entry_data["device_id"] = device_id

        if not http_token:
            _LOGGER.warning("HTTP Token missing for %s.", device_sn)
        if device_id != entry.data.get(CONF_DEVICE_ID):
            _LOGGER.warning("Using SN %s as Device ID.", device_sn)

        session = async_get_clientsession(hass)
        api_client = LumentreeHttpApiClient(session)
        api_client.set_token(http_token)
        api_client.set_reauth_device_id(device_id)
        entry_data["api_client"] = api_client

        _LOGGER.info("Fetching device info via HTTP for %s...", device_id)
        try:
            device_api_info = await api_client.get_device_info(device_id)
        except (ApiException, AuthException) as api_err:
            _LOGGER.error("Failed initial device info fetch %s: %s.", device_id, api_err)
            raise ConfigEntryNotReady(f"Failed device info: {api_err}") from api_err
        if "_error" in device_api_info:
            _LOGGER.error("API error getting device info: %s", device_api_info["_error"])
            raise ConfigEntryNotReady(f"API error: {device_api_info['_error']}")
        entry_data["device_api_info"] = device_api_info
        _LOGGER.info(
            "Stored API info: Model=%s, ID=%s",
            device_api_info.get("deviceType"),
            device_api_info.get("deviceId"),
        )

        mqtt_client = LumentreeMqttClient(hass, entry, device_sn, device_id)
        entry_data["mqtt_client"] = mqtt_client
        try:
            await mqtt_client.connect()
        except ConnectionRefusedError as mqtt_err:
            # A broker that is down or slow at boot is transient.  Returning
            # False here (what the generic handler below does) left the entry
            # failed until someone reloaded it by hand.
            raise ConfigEntryNotReady(f"MQTT broker not reachable: {mqtt_err}") from mqtt_err

        aggregator = StatsAggregator(hass, api_client, device_id)
        entry_data[_KEY_AGGREGATOR] = aggregator

        daily_coord = DailyStatsCoordinator(hass, api_client, aggregator, device_sn)
        monthly_coord = MonthlyStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        yearly_coord = YearlyStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        total_coord = TotalStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        entry_data.update(
            {
                "daily_coordinator": daily_coord,
                "monthly_coordinator": monthly_coord,
                "yearly_coordinator": yearly_coord,
                "total_coordinator": total_coord,
            }
        )

        # Prime daily coordinator first (non-blocking), then stats coordinators after delay
        # This avoids race condition where monthly/yearly/total read empty cache
        # before backfill has populated it.
        #
        # These use async_refresh, not async_config_entry_first_refresh: the
        # latter raises ConfigEntryError unless the entry is still
        # SETUP_IN_PROGRESS, and by the time the staggered sleep below elapses
        # setup has returned and the entry is LOADED -- which silently left
        # every monthly/yearly/total sensor stuck at `unknown`.
        async def _prime_coordinators_staggered() -> None:
            try:
                await daily_coord.async_refresh()
            except Exception as e:
                _LOGGER.warning("Daily coordinator first refresh failed: %s", e)
            # Give backfill time to populate cache, then refresh stats coordinators
            await asyncio.sleep(_STAGGER_DELAY_SECONDS)
            for coord, label in (
                (monthly_coord, "monthly"),
                (yearly_coord, "yearly"),
                (total_coord, "total"),
            ):
                try:
                    await coord.async_refresh()
                except Exception as e:
                    _LOGGER.warning("%s coordinator refresh failed: %s", label, e)

        # Entry-scoped background tasks are cancelled when the entry unloads.
        # A plain hass task outlived a reload and kept refreshing coordinators
        # and writing the cache for an entry that no longer existed.
        entry.async_create_background_task(
            hass, _prime_coordinators_staggered(), f"lumentree_prime_{device_sn}"
        )

        poll_count = 0

        async def _async_poll_data(now: datetime.datetime | None = None) -> None:
            """Ask the inverter for a fresh frame over MQTT."""
            nonlocal poll_count
            if mqtt_client is None or not mqtt_client.is_connected:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT %s not connected yet, skipping poll", device_sn)
                return
            try:
                await mqtt_client.async_request_data()
                poll_count += 1
                if poll_count % 6 == 0:
                    await mqtt_client.async_request_battery_cells()
            except Exception as poll_err:
                _LOGGER.error("MQTT poll error %s: %s", device_sn, poll_err)

        polling_interval = datetime.timedelta(seconds=DEFAULT_POLLING_INTERVAL)
        entry.async_on_unload(async_track_time_interval(hass, _async_poll_data, polling_interval))
        _LOGGER.info("Started MQTT polling %s for %s", polling_interval, device_sn)

        async def _async_stop_mqtt(event: Event) -> None:
            """Disconnect MQTT client on Home Assistant stop."""
            if mqtt_client is not None:
                _LOGGER.info("Disconnecting MQTT %s.", device_sn)
                await mqtt_client.disconnect()

        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_mqtt)
        )

        # Auto backfill: first-run (background) and nightly delta
        should_purge_on_startup = entry.options.get("purge_and_backfill_on_startup", False)

        async def _first_run_backfill() -> None:
            try:
                if should_purge_on_startup:
                    _LOGGER.warning(
                        "PURGE_AND_BACKFILL_ON_STARTUP is enabled - purging all cache..."
                    )
                    result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
                    _LOGGER.info("Purge result: %s", result)
                stats = await aggregator.smart_backfill(max_years=5, optimize_cache=True)
                _LOGGER.info("Auto backfill: completed 5-year history - %s", stats)

                # Auto-disable purge_and_backfill_on_startup after successful backfill
                if should_purge_on_startup:
                    new_options = {**entry.options, "purge_and_backfill_on_startup": False}
                    hass.config_entries.async_update_entry(entry, options=new_options)
                    _LOGGER.info(
                        "PURGE_AND_BACKFILL_ON_STARTUP has been automatically set to False"
                    )
            except Exception as err:
                _LOGGER.error("Auto backfill initial failed: %s", err)

        async def _nightly_delta(now: datetime.datetime | None = None) -> None:
            try:
                yesterday = today_in_ha(hass) - datetime.timedelta(days=1)
                _LOGGER.info("Nightly backfill for %s", yesterday)
                await aggregator.backfill_days(yesterday, yesterday)
                stats = await aggregator.smart_backfill(max_years=1, optimize_cache=False)
                if stats.get("days_added", 0) or stats.get("days_updated", 0):
                    _LOGGER.info(
                        "Nightly smart backfill: added %s, updated %s days",
                        stats.get("days_added", 0),
                        stats.get("days_updated", 0),
                    )
            except Exception as err:
                _LOGGER.error("Nightly backfill error: %s", err)

        entry.async_create_background_task(
            hass, _first_run_backfill(), f"lumentree_backfill_{device_sn}"
        )

        # A fixed local time, not "24h after setup": the old interval ran at
        # whatever hour HA last restarted, which is not "nightly" at all.
        entry.async_on_unload(
            async_track_time_change(
                hass, _nightly_delta, hour=_NIGHTLY_HOUR, minute=_NIGHTLY_MINUTE, second=0
            )
        )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info("Setup complete for %s (SN/ID: %s)", entry.title, device_sn)
        return True

    except ConfigEntryNotReady as e:
        _LOGGER.warning("Setup failed %s: %s. Will retry.", entry.title, e)
        await _async_abort_setup(hass, entry, mqtt_client)
        raise
    except Exception:
        _LOGGER.exception("Unexpected setup error %s", entry.title)
        await _async_abort_setup(hass, entry, mqtt_client)
        return False


async def _async_abort_setup(
    hass: HomeAssistant, entry: ConfigEntry, mqtt_client: LumentreeMqttClient | None
) -> None:
    """Undo a partial setup.

    Timers and listeners were registered with ``entry.async_on_unload`` and
    the background tasks with ``entry.async_create_background_task``; Home
    Assistant runs and cancels those itself when setup fails.  What is left is
    the MQTT connection and the entry's slot in ``hass.data``.
    """
    if mqtt_client is not None:
        try:
            await mqtt_client.disconnect()
        except Exception as err:
            _LOGGER.debug("MQTT disconnect during setup cleanup failed: %s", err)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    device_sn = entry.data.get(CONF_DEVICE_SN, "unknown")
    _LOGGER.info("Unloading Lumentree: %s (SN/ID: %s)", entry.title, device_sn)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        # Platforms are still loaded and still reading these objects; tearing
        # them down now would leave live entities on a dead connection.
        _LOGGER.warning("Unload %s: platforms did not unload, keeping runtime data", entry.title)
        return False

    entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if not entry_data:
        _LOGGER.warning("No entry data %s to clean.", entry.entry_id)
        return True

    mqtt_client = entry_data.get("mqtt_client")
    if isinstance(mqtt_client, LumentreeMqttClient):
        try:
            await mqtt_client.disconnect()
        except Exception as disconnect_err:
            _LOGGER.warning("Error disconnecting MQTT during unload: %s", disconnect_err)

    for coord_key in (
        "daily_coordinator",
        "monthly_coordinator",
        "yearly_coordinator",
        "total_coordinator",
    ):
        coord = entry_data.get(coord_key)
        if coord is not None:
            try:
                await coord.async_shutdown()
            except Exception as coord_err:
                _LOGGER.warning("Error shutting down %s %s: %s", coord_key, device_sn, coord_err)

    _LOGGER.info("Unload %s: OK.", entry.title)
    return True


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def _target_entries(hass: HomeAssistant, call: ServiceCall) -> list[dict[str, Any]]:
    """Return the runtime data of every inverter a service call applies to."""
    loaded = [
        data
        for data in hass.data.get(DOMAIN, {}).values()
        if isinstance(data, dict) and _KEY_AGGREGATOR in data
    ]
    wanted = call.data.get(ATTR_DEVICE_SN)
    if wanted:
        wanted = str(wanted).strip()
        loaded = [d for d in loaded if wanted in (d.get("device_sn"), d.get("device_id"))]
        if not loaded:
            raise HomeAssistantError(f"No loaded Lumentree inverter with serial {wanted!r}")
    elif not loaded:
        raise HomeAssistantError("No Lumentree inverter is loaded")
    return loaded


def _required_year(call: ServiceCall) -> int:
    """Read the mandatory ``year`` service field, or raise a readable error.

    Indexing call.data directly raises a bare KeyError out of the
    service call, which reaches the user as an unhelpful traceback.
    """
    raw = call.data.get("year")
    if raw is None:
        raise HomeAssistantError("The 'year' field is required for this service.")
    try:
        return int(raw)
    except (TypeError, ValueError) as err:
        raise HomeAssistantError(f"'year' must be a number, got {raw!r}") from err


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services (idempotent)."""

    def _per_entry(
        handler: Callable[[HomeAssistant, dict[str, Any], ServiceCall], Awaitable[None]],
    ) -> Callable[[ServiceCall], Awaitable[None]]:
        async def _run(call: ServiceCall) -> None:
            for entry_data in _target_entries(hass, call):
                await handler(hass, entry_data, call)

        return _run

    services: dict[str, Callable[[HomeAssistant, dict[str, Any], ServiceCall], Awaitable[None]]] = {
        "backfill_now": _svc_backfill,
        "recompute_month_year": _svc_recompute,
        "optimize_cache": _svc_optimize_cache,
        "smart_backfill": _svc_smart_backfill,
        "purge_cache": _svc_purge,
        "purge_all_cache": _svc_purge_all,
        "purge_and_backfill": _svc_purge_and_backfill,
        "backfill_all": _svc_backfill_all,
        "backfill_gaps": _svc_backfill_gaps,
        "backfill_empty_dates": _svc_backfill_empty_dates,
        "mark_empty_dates": _svc_mark_empty_dates,
        "mark_coverage_range": _svc_mark_coverage_range,
        "enable_purge_on_startup": _svc_enable_purge_on_startup,
        "disable_purge_on_startup": _svc_disable_purge_on_startup,
    }
    for name, handler in services.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, _per_entry(handler))


async def _svc_backfill(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    days = int(call.data.get("days", 365))
    await data[_KEY_AGGREGATOR].backfill_last_n_days(days)


async def _svc_recompute(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    # Recompute aggregates for the current year.
    #
    # Loading, recomputing and saving are all blocking file/CPU work, so
    # they run in one executor job.  load_year is called with
    # auto_recompute=False: it would otherwise recompute internally and
    # then this handler would recompute the same cache a second time.
    device_id = data["device_id"]
    year = today_in_ha(hass).year

    def _recompute() -> None:
        c = cache_io.load_year(device_id, year, auto_recompute=False)
        cache_io.recompute_aggregates(c)
        cache_io.save_year(device_id, year, c)

    await hass.async_add_executor_job(_recompute)


async def _svc_optimize_cache(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    """Optimize cache by removing empty days."""
    from .services import cache_optimizer

    device_id = data["device_id"]
    all_years = call.data.get("all_years", False)
    dry_run = call.data.get("dry_run", False)

    if all_years:
        max_years = int(call.data.get("max_years", 10))
        result = await hass.async_add_executor_job(
            cache_optimizer.optimize_all_years, device_id, max_years, dry_run
        )
        summary = result["summary"]
        _LOGGER.info(
            "Optimize cache (all years): removed %s empty days, kept %s days, "
            "size reduction: %.1f%%",
            summary["total_removed"],
            summary["total_kept"],
            summary["total_size_reduction_percent"],
        )
        return

    year = int(call.data.get("year", today_in_ha(hass).year))
    result = await hass.async_add_executor_job(
        cache_optimizer.optimize_year_cache, device_id, year, dry_run
    )
    if result["status"] == "optimized":
        _LOGGER.info(
            "Optimize cache (%s): removed %s empty days, kept %s days, size reduction: %.1f%%",
            year,
            result["removed"],
            result["kept"],
            result["size_reduction_percent"],
        )
    else:
        _LOGGER.warning("Optimize cache (%s): %s", year, result["status"])


async def _svc_purge(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    year = int(call.data.get("year", today_in_ha(hass).year))
    await hass.async_add_executor_job(cache_io.purge_year, data["device_id"], year)


async def _svc_purge_all(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    """Purge all cache files for this device."""
    device_id = data["device_id"]
    _LOGGER.info("Purging all cache for device %s", device_id)
    result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
    _LOGGER.info("Purge all cache result: %s", result)


async def _svc_purge_and_backfill(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    """Purge all cache and backfill from scratch using smart backfill."""
    device_id = data["device_id"]
    max_years_val = call.data.get("max_years")
    max_years = int(max_years_val) if max_years_val is not None else 5
    optimize_cache = call.data.get("optimize_cache", True)

    _LOGGER.warning(
        "Purging ALL cache for device %s and starting fresh smart backfill...", device_id
    )
    result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
    _LOGGER.info("Purge result: %s", result)
    stats = await data[_KEY_AGGREGATOR].smart_backfill(
        max_years=max_years, optimize_cache=optimize_cache
    )
    _LOGGER.info("Purge and smart backfill completed: %s", stats)


async def _svc_smart_backfill(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    """Smart backfill using the getMonthData API."""
    max_years = int(call.data.get("max_years", 10))
    optimize_cache = call.data.get("optimize_cache", True)
    stats = await data[_KEY_AGGREGATOR].smart_backfill(
        max_years=max_years, optimize_cache=optimize_cache
    )
    _LOGGER.info("Smart backfill completed: %s", stats)


async def _svc_backfill_all(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    max_years_val = call.data.get("max_years")
    max_years = int(max_years_val) if max_years_val is not None else None
    empty_streak = int(call.data.get("empty_streak", 14))
    await data[_KEY_AGGREGATOR].backfill_all(max_years=max_years, empty_streak=empty_streak)


async def _svc_backfill_gaps(hass: HomeAssistant, data: dict[str, Any], call: ServiceCall) -> None:
    max_years = int(call.data.get("max_years", 3))
    max_days_per_run = int(call.data.get("max_days_per_run", 30))
    await data[_KEY_AGGREGATOR].backfill_gaps(
        max_years=max_years, max_days_per_run=max_days_per_run
    )


async def _svc_backfill_empty_dates(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    max_years = int(call.data.get("max_years", 5))
    max_days_per_run = int(call.data.get("max_days_per_run", 100))
    result = await data[_KEY_AGGREGATOR].backfill_empty_dates(
        max_years=max_years, max_days_per_run=max_days_per_run
    )
    _LOGGER.info(
        "backfill_empty_dates service completed: recovered=%s, confirmed_empty=%s, errors=%s",
        result.get("recovered", 0),
        result.get("confirmed_empty", 0),
        result.get("errors", 0),
    )


def _set_purge_on_startup(hass: HomeAssistant, entry: ConfigEntry, enabled: bool) -> None:
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "purge_and_backfill_on_startup": enabled}
    )


async def _svc_enable_purge_on_startup(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    """Enable purge and backfill on next startup."""
    _set_purge_on_startup(hass, data["entry"], True)
    _LOGGER.warning(
        "purge_and_backfill_on_startup has been enabled for %s. It will run on next "
        "restart and auto-disable after completion.",
        data["device_sn"],
    )


async def _svc_disable_purge_on_startup(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    """Disable purge and backfill on startup."""
    _set_purge_on_startup(hass, data["entry"], False)
    _LOGGER.info("purge_and_backfill_on_startup has been disabled for %s.", data["device_sn"])


async def _svc_mark_empty_dates(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    device_id = data["device_id"]
    year = _required_year(call)
    dates = list(call.data.get("dates", []))

    def _mark() -> None:
        c = cache_io.load_year(device_id, year, auto_recompute=False)
        for ds in dates:
            c = cache_io.mark_empty(c, ds)
        cache_io.save_year(device_id, year, c)

    await hass.async_add_executor_job(_mark)


async def _svc_mark_coverage_range(
    hass: HomeAssistant, data: dict[str, Any], call: ServiceCall
) -> None:
    device_id = data["device_id"]
    year = _required_year(call)
    earliest = call.data.get("earliest")
    latest = call.data.get("latest")

    def _mark() -> None:
        c = cache_io.load_year(device_id, year, auto_recompute=False)
        meta = c.setdefault("meta", {})
        cov = meta.setdefault("coverage", {"earliest": None, "latest": None})
        if earliest is not None:
            cov["earliest"] = earliest
        if latest is not None:
            cov["latest"] = latest
        cache_io.save_year(device_id, year, c)

    await hass.async_add_executor_job(_mark)
