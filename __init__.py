"""Lumentree Inverter integration for Home Assistant."""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    _LOGGER,
    CONF_DEVICE_ID,
    CONF_DEVICE_SN,
    CONF_HTTP_TOKEN,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
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

# Delay before the monthly/yearly/total coordinators are warmed, so the backfill
# that the daily coordinator kicks off has time to fill the cache they read.
# Module-level so a test can shrink it; ten real seconds per entry otherwise
# dominates the end-to-end suite.
_STAGGER_DELAY_SECONDS = 10.0


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Lumentree integration."""
    # Config flow is handled automatically by Home Assistant
    # when config_flow: true is set in manifest.json
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lumentree from a config entry."""
    _LOGGER.info(f"Setting up Lumentree: {entry.title} ({entry.entry_id})")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    api_client: LumentreeHttpApiClient | None = None
    mqtt_client: LumentreeMqttClient | None = None
    remove_interval: Callable | None = None
    remove_nightly: Callable | None = None

    try:
        device_sn = entry.data[CONF_DEVICE_SN]
        device_id = entry.data.get(CONF_DEVICE_ID, device_sn)
        http_token = entry.data.get(CONF_HTTP_TOKEN)

        if not http_token:
            _LOGGER.warning(f"HTTP Token missing for {device_sn}.")
        if device_id != entry.data.get(CONF_DEVICE_ID):
            _LOGGER.warning(f"Using SN {device_sn} as Device ID.")

        session = async_get_clientsession(hass)
        api_client = LumentreeHttpApiClient(session)
        api_client.set_token(http_token)
        hass.data[DOMAIN][entry.entry_id]["api_client"] = api_client

        _LOGGER.info(f"Fetching device info via HTTP for {device_id}...")
        try:
            device_api_info = await api_client.get_device_info(device_id)
            if "_error" in device_api_info:
                _LOGGER.error(f"API error getting device info: {device_api_info['_error']}")
                raise ConfigEntryNotReady(f"API error: {device_api_info['_error']}")
            hass.data[DOMAIN][entry.entry_id]["device_api_info"] = device_api_info
            _LOGGER.info(
                f"Stored API info: Model={device_api_info.get('deviceType')}, "
                f"ID={device_api_info.get('deviceId')}"
            )
        except (ApiException, AuthException) as api_err:
            _LOGGER.error(f"Failed initial device info fetch {device_id}: {api_err}.")
            raise ConfigEntryNotReady(f"Failed device info: {api_err}") from api_err

        mqtt_client = LumentreeMqttClient(hass, entry, device_sn, device_id)
        hass.data[DOMAIN][entry.entry_id]["mqtt_client"] = mqtt_client
        await mqtt_client.connect()

        # Create aggregators and coordinators
        aggregator = StatsAggregator(hass, api_client, device_id)
        hass.data[DOMAIN][entry.entry_id]["aggregator"] = aggregator

        daily_coord = DailyStatsCoordinator(hass, api_client, aggregator, device_sn)
        monthly_coord = MonthlyStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        yearly_coord = YearlyStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        total_coord = TotalStatsCoordinator(hass, aggregator, device_sn, entry.entry_id)
        hass.data[DOMAIN][entry.entry_id].update(
            {
                "daily_coordinator": daily_coord,
                "monthly_coordinator": monthly_coord,
                "yearly_coordinator": yearly_coord,
                "total_coordinator": total_coord,
            }
        )
        _LOGGER.info(f"Created total coordinator for {device_sn}")

        # Prime daily coordinator first (non-blocking), then stats coordinators after delay
        # This avoids race condition where monthly/yearly/total read empty cache
        # before backfill has populated it.
        #
        # These use async_refresh, not async_config_entry_first_refresh: the
        # latter raises ConfigEntryError unless the entry is still
        # SETUP_IN_PROGRESS, and by the time the staggered sleep below elapses
        # setup has returned and the entry is LOADED -- which silently left
        # every monthly/yearly/total sensor stuck at `unknown`.
        async def _prime_coordinators_staggered():
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

        hass.async_create_task(_prime_coordinators_staggered())

        polling_interval = datetime.timedelta(seconds=DEFAULT_POLLING_INTERVAL)
        _poll_count = 0

        async def _async_poll_data(now=None):
            """Poll data from MQTT client."""
            nonlocal _poll_count
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("MQTT Poll %s.", device_sn)
            domain_data = hass.data.get(DOMAIN)
            if not domain_data:
                _LOGGER.warning("Lumentree domain data gone. Stop poll.")
                return
            entry_data = domain_data.get(entry.entry_id)
            if not entry_data:
                _LOGGER.warning("Entry data missing %s. Stop poll.", entry.entry_id)
                nonlocal remove_interval
                current_timer = remove_interval
                if callable(current_timer):
                    try:
                        current_timer()
                        _LOGGER.info("MQTT poll timer cancelled %s.", device_sn)
                        remove_interval = None
                    except Exception as timer_err:
                        _LOGGER.error("Error cancel timer %s: %s", device_sn, timer_err)
                return

            active_mqtt_client = entry_data.get("mqtt_client")
            if not isinstance(active_mqtt_client, LumentreeMqttClient):
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT client not initialized for %s", device_sn)
                return
            if not active_mqtt_client.is_connected:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT %s not connected yet, skipping poll", device_sn)
                return
            try:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Requesting MQTT (main data) %s...", device_sn)
                await active_mqtt_client.async_request_data()
                _poll_count += 1
                if _poll_count % 6 == 0:
                    await active_mqtt_client.async_request_battery_cells()
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT request sent %s.", device_sn)
            except Exception as poll_err:
                _LOGGER.error("MQTT poll error %s: %s", device_sn, poll_err)

        remove_interval = async_track_time_interval(hass, _async_poll_data, polling_interval)
        _LOGGER.info(f"Started MQTT polling {polling_interval} for {device_sn}")

        @callback
        def _cancel_timer_on_unload():
            """Cancel the polling timer when the entry is unloaded."""
            nonlocal remove_interval
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Unload: Cancelling MQTT timer for %s.", device_sn)
            current_timer = remove_interval
            if callable(current_timer):
                try:
                    current_timer()
                    _LOGGER.info(f"MQTT polling timer cancelled for {device_sn} during unload.")
                    remove_interval = None
                except Exception as timer_err:
                    _LOGGER.error(f"Error cancelling timer during unload {device_sn}: {timer_err}")

        async def _async_stop_mqtt(event: Event) -> None:
            """Disconnect MQTT client on Home Assistant stop."""
            _LOGGER.info("Home Assistant stop event received.")
            client_to_stop = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("mqtt_client")
            if isinstance(client_to_stop, LumentreeMqttClient):
                _LOGGER.info(f"Disconnecting MQTT {device_sn}.")
                await client_to_stop.disconnect()

        entry.async_on_unload(_cancel_timer_on_unload)
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_mqtt)
        )

        # Services: backfill_now, recompute_month_year, purge_cache, backfill_all, backfill_gaps,
        #            mark_empty_dates, mark_coverage_range

        def _required_year(call) -> int:
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

        async def _svc_backfill(call):
            days = int(call.data.get("days", 365))
            await aggregator.backfill_last_n_days(days)

        async def _svc_recompute(call):
            # Recompute aggregates for the current year.
            #
            # Loading, recomputing and saving are all blocking file/CPU work, so
            # they run in one executor job.  load_year is called with
            # auto_recompute=False: it would otherwise recompute internally and
            # then this handler would recompute the same cache a second time.
            now = datetime.datetime.now()

            def _recompute() -> None:
                c = cache_io.load_year(device_id, now.year, auto_recompute=False)
                cache_io.recompute_aggregates(c)
                cache_io.save_year(device_id, now.year, c)

            await hass.async_add_executor_job(_recompute)

        async def _svc_optimize_cache(call):
            """Optimize cache by removing empty days."""
            from .services import cache_optimizer

            all_years = call.data.get("all_years", False)
            dry_run = call.data.get("dry_run", False)

            if all_years:
                max_years = int(call.data.get("max_years", 10))
                result = await hass.async_add_executor_job(
                    cache_optimizer.optimize_all_years, device_id, max_years, dry_run
                )
                summary = result["summary"]
                _LOGGER.info(
                    f"Optimize cache (all years): removed {summary['total_removed']} empty days, "
                    f"kept {summary['total_kept']} days, "
                    f"size reduction: {summary['total_size_reduction_percent']:.1f}%"
                )
            else:
                year = int(call.data.get("year", datetime.datetime.now().year))
                result = await hass.async_add_executor_job(
                    cache_optimizer.optimize_year_cache, device_id, year, dry_run
                )
                if result["status"] == "optimized":
                    _LOGGER.info(
                        f"Optimize cache ({year}): removed {result['removed']} empty days, "
                        f"kept {result['kept']} days, "
                        f"size reduction: {result['size_reduction_percent']:.1f}%"
                    )
                else:
                    _LOGGER.warning(f"Optimize cache ({year}): {result['status']}")

        async def _svc_purge(call):
            year = int(call.data.get("year", datetime.datetime.now().year))
            await hass.async_add_executor_job(cache_io.purge_year, device_id, year)

        async def _svc_purge_all(call):
            """Purge all cache files for this device."""
            _LOGGER.info(f"Purging all cache for device {device_id}")
            result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
            _LOGGER.info(f"Purge all cache result: {result}")

        async def _svc_purge_and_backfill(call):
            """Purge all cache and backfill from scratch using smart backfill."""
            max_years_val = call.data.get("max_years")
            max_years = int(max_years_val) if max_years_val is not None else 5
            optimize_cache = call.data.get("optimize_cache", True)

            _LOGGER.warning(
                f"Purging ALL cache for device {device_id} and starting fresh smart backfill..."
            )
            result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
            _LOGGER.info(f"Purge result: {result}")

            _LOGGER.info(f"Starting smart backfill for {max_years} years...")
            stats = await aggregator.smart_backfill(
                max_years=max_years, optimize_cache=optimize_cache
            )
            _LOGGER.info(f"Purge and smart backfill completed: {stats}")

        async def _svc_smart_backfill(call):
            """Smart backfill using getYearData/getMonthData APIs."""
            max_years = int(call.data.get("max_years", 10))
            optimize_cache = call.data.get("optimize_cache", True)
            stats = await aggregator.smart_backfill(
                max_years=max_years, optimize_cache=optimize_cache
            )
            _LOGGER.info(f"Smart backfill completed: {stats}")

        async def _svc_backfill_all(call):
            max_years_val = call.data.get("max_years")
            max_years = int(max_years_val) if max_years_val is not None else None
            empty_streak = int(call.data.get("empty_streak", 14))
            await aggregator.backfill_all(max_years=max_years, empty_streak=empty_streak)

        async def _svc_backfill_gaps(call):
            max_years = int(call.data.get("max_years", 3))
            max_days_per_run = int(call.data.get("max_days_per_run", 30))
            await aggregator.backfill_gaps(max_years=max_years, max_days_per_run=max_days_per_run)

        async def _svc_backfill_empty_dates(call):
            max_years = int(call.data.get("max_years", 5))
            max_days_per_run = int(call.data.get("max_days_per_run", 100))
            result = await aggregator.backfill_empty_dates(
                max_years=max_years, max_days_per_run=max_days_per_run
            )
            _LOGGER.info(
                f"backfill_empty_dates service completed: "
                f"recovered={result.get('recovered', 0)}, "
                f"confirmed_empty={result.get('confirmed_empty', 0)}, "
                f"errors={result.get('errors', 0)}"
            )

        async def _svc_enable_purge_on_startup(call):
            """Enable purge and backfill on next startup."""
            new_options = entry.options.copy()
            new_options["purge_and_backfill_on_startup"] = True
            hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.warning(
                "purge_and_backfill_on_startup has been enabled. It will run on next restart and auto-disable after completion."
            )

        async def _svc_disable_purge_on_startup(call):
            """Disable purge and backfill on startup."""
            new_options = entry.options.copy()
            new_options["purge_and_backfill_on_startup"] = False
            hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.info("purge_and_backfill_on_startup has been disabled.")

        async def _svc_mark_empty_dates(call):
            year = _required_year(call)
            dates = list(call.data.get("dates", []))

            def _mark() -> None:
                c = cache_io.load_year(device_id, year, auto_recompute=False)
                for ds in dates:
                    c = cache_io.mark_empty(c, ds)
                cache_io.save_year(device_id, year, c)

            await hass.async_add_executor_job(_mark)

        async def _svc_mark_coverage_range(call):
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

        hass.services.async_register(DOMAIN, "backfill_now", _svc_backfill)
        hass.services.async_register(DOMAIN, "recompute_month_year", _svc_recompute)
        hass.services.async_register(DOMAIN, "optimize_cache", _svc_optimize_cache)
        hass.services.async_register(DOMAIN, "smart_backfill", _svc_smart_backfill)
        hass.services.async_register(DOMAIN, "purge_cache", _svc_purge)
        hass.services.async_register(DOMAIN, "purge_all_cache", _svc_purge_all)
        hass.services.async_register(DOMAIN, "purge_and_backfill", _svc_purge_and_backfill)
        hass.services.async_register(DOMAIN, "backfill_all", _svc_backfill_all)
        hass.services.async_register(DOMAIN, "backfill_gaps", _svc_backfill_gaps)
        hass.services.async_register(DOMAIN, "backfill_empty_dates", _svc_backfill_empty_dates)
        hass.services.async_register(DOMAIN, "mark_empty_dates", _svc_mark_empty_dates)
        hass.services.async_register(DOMAIN, "mark_coverage_range", _svc_mark_coverage_range)
        hass.services.async_register(
            DOMAIN, "enable_purge_on_startup", _svc_enable_purge_on_startup
        )
        hass.services.async_register(
            DOMAIN, "disable_purge_on_startup", _svc_disable_purge_on_startup
        )

        # Auto backfill: first-run (background) and nightly delta
        # Check if we need to purge and backfill on startup (from entry options or default False)
        should_purge_on_startup = entry.options.get("purge_and_backfill_on_startup", False)

        async def _first_run_backfill() -> None:
            try:
                if should_purge_on_startup:
                    _LOGGER.warning(
                        "PURGE_AND_BACKFILL_ON_STARTUP is enabled - purging all cache..."
                    )
                    result = await hass.async_add_executor_job(cache_io.purge_device, device_id)
                    _LOGGER.info(f"Purge result: {result}")
                    _LOGGER.warning("Starting smart backfill for 5 years...")
                    # Use smart backfill for faster performance
                    stats = await aggregator.smart_backfill(max_years=5, optimize_cache=True)
                    _LOGGER.info(f"Smart backfill completed: {stats}")
                else:
                    _LOGGER.info(
                        "Auto backfill: starting smart backfill for last 5 years (background)"
                    )
                    # Use smart backfill - much faster than daily backfill
                    stats = await aggregator.smart_backfill(max_years=5, optimize_cache=True)
                    _LOGGER.info(f"Auto backfill: completed 5-year history - {stats}")

                # Auto-disable purge_and_backfill_on_startup after successful backfill
                if should_purge_on_startup:
                    _LOGGER.info(
                        "Backfill completed successfully. Auto-disabling PURGE_AND_BACKFILL_ON_STARTUP..."
                    )
                    # Update entry options to disable the flag
                    new_options = entry.options.copy()
                    new_options["purge_and_backfill_on_startup"] = False
                    hass.config_entries.async_update_entry(entry, options=new_options)
                    _LOGGER.info(
                        "PURGE_AND_BACKFILL_ON_STARTUP has been automatically set to False"
                    )
            except Exception as err:
                _LOGGER.error(f"Auto backfill initial failed: {err}")

        async def _nightly_delta(now=None):
            try:
                today = datetime.date.today()
                yesterday = today - datetime.timedelta(days=1)
                _LOGGER.info("Nightly backfill: %s → %s", yesterday, today)
                # Backfill yesterday and today using daily API (for accuracy)
                await aggregator.backfill_days(yesterday, today)
                # Use smart backfill to fill gaps in recent months (much faster)
                # Only check last 3 months for gaps
                stats = await aggregator.smart_backfill(max_years=1, optimize_cache=False)
                if stats.get("days_added", 0) > 0:
                    _LOGGER.info(f"Nightly smart backfill: added {stats['days_added']} days")
            except Exception as err:
                _LOGGER.error(f"Nightly backfill error: {err}")

        # Kick off initial backfill without blocking setup
        hass.async_create_task(_first_run_backfill())

        # Schedule nightly job every 24h — store before risky step so we can clean up on failure
        remove_nightly = async_track_time_interval(
            hass, _nightly_delta, datetime.timedelta(hours=24)
        )
        hass.data[DOMAIN][entry.entry_id]["remove_nightly"] = remove_nightly

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info("Setup complete for %s (SN/ID: %s)", entry.title, device_sn)
        return True

    except ConfigEntryNotReady as e:
        _LOGGER.warning("Setup failed %s: %s. Cleaning up...", entry.title, e)
        # Test the local name, not the dict key: the two are set together two
        # lines apart, and keying off the dict would call None if they ever drift.
        if remove_nightly is not None:
            try:
                remove_nightly()
            except Exception as cleanup_err:
                # Best-effort: setup is already failing, this must not mask it.
                _LOGGER.debug(f"remove_nightly failed during cleanup of {device_sn}: {cleanup_err}")
        if isinstance(mqtt_client, LumentreeMqttClient):
            await mqtt_client.disconnect()
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    except Exception:
        _LOGGER.exception("Unexpected setup error %s", entry.title)
        if remove_nightly is not None:
            try:
                remove_nightly()
            except Exception as cleanup_err:
                # Best-effort: the real failure is logged just above.
                _LOGGER.debug(f"remove_nightly failed during cleanup of {device_sn}: {cleanup_err}")
        if isinstance(mqtt_client, LumentreeMqttClient):
            await mqtt_client.disconnect()
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    device_sn = entry.data.get(CONF_DEVICE_SN, "unknown")
    _LOGGER.info(f"Unloading Lumentree: {entry.title} (SN/ID: {device_sn})")

    # Unload platforms first (this will trigger entity cleanup including dispatcher listeners)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Get entry data before removing it
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    if entry_data:
        # Disconnect MQTT client first (this will cancel all timers and unsubscribe)
        mqtt_client = entry_data.get("mqtt_client")
        if isinstance(mqtt_client, LumentreeMqttClient):
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Disconnecting MQTT %s.", device_sn)
            try:
                await mqtt_client.disconnect()
            except Exception as disconnect_err:
                _LOGGER.warning(f"Error disconnecting MQTT during unload: {disconnect_err}")

        # Cancel nightly timer if any (backup cleanup, though disconnect should handle it)
        rm_nightly = entry_data.get("remove_nightly")
        if callable(rm_nightly):
            try:
                rm_nightly()
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Cancelled nightly timer for %s.", device_sn)
            except Exception as timer_err:
                _LOGGER.warning(f"Error cancelling nightly timer {device_sn}: {timer_err}")

        # Cleanup coordinators (they should be cleaned up by platform unload, but ensure cleanup)
        for coord_key in [
            "daily_coordinator",
            "monthly_coordinator",
            "yearly_coordinator",
            "total_coordinator",
        ]:
            coord = entry_data.get(coord_key)
            if coord and hasattr(coord, "async_shutdown"):
                try:
                    await coord.async_shutdown()
                except Exception as coord_err:
                    _LOGGER.warning(f"Error shutting down {coord_key} {device_sn}: {coord_err}")

        # Cleanup aggregator if any
        aggregator = entry_data.get("aggregator")
        if aggregator and hasattr(aggregator, "cleanup"):
            try:
                aggregator.cleanup()
            except Exception as cleanup_err:
                # Best-effort during unload; a failure here must not sink the unload.
                _LOGGER.debug(f"Aggregator cleanup failed for {device_sn}: {cleanup_err}")

        # Cleanup API client reference (session is managed by HA)
        entry_data.pop("api_client", None)

        # Remove entry data from domain
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Removed entry data %s.", entry.entry_id)
    else:
        _LOGGER.warning(f"No entry data {entry.entry_id} to clean.")

    _LOGGER.info(f"Unload {entry.title}: {'OK' if unload_ok else 'Failed'}.")
    return unload_ok
