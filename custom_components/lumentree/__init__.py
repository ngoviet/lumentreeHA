"""Lumentree Inverter integration for Home Assistant."""

import asyncio
import datetime
import logging
from contextlib import suppress
from typing import Optional, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    DOMAIN, _LOGGER, CONF_DEVICE_SN, CONF_DEVICE_ID, CONF_HTTP_TOKEN,
    DEFAULT_POLLING_INTERVAL
)
from .core.api_client import LumentreeHttpApiClient, AuthException, ApiException
from .core.mqtt_client import LumentreeMqttClient
from .coordinators.daily_coordinator import DailyStatsCoordinator
from .coordinators.monthly_coordinator import MonthlyStatsCoordinator
from .coordinators.yearly_coordinator import YearlyStatsCoordinator
from .coordinators.total_coordinator import TotalStatsCoordinator
from .services.aggregator import StatsAggregator
from .services import cache as cache_io

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lumentree from a config entry."""
    _LOGGER.info(f"Setting up Lumentree: {entry.title} ({entry.entry_id})")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}
    
    api_client: Optional[LumentreeHttpApiClient] = None
    mqtt_client: Optional[LumentreeMqttClient] = None
    remove_interval: Optional[Callable] = None
    remove_nightly: Optional[Callable] = None

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
            hass.data[DOMAIN][entry.entry_id]['device_api_info'] = device_api_info
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

        daily_coord = DailyStatsCoordinator(hass, api_client, device_sn)
        monthly_coord = MonthlyStatsCoordinator(hass, aggregator, device_sn)
        yearly_coord = YearlyStatsCoordinator(hass, aggregator, device_sn)
        total_coord = TotalStatsCoordinator(hass, aggregator, device_sn)
        hass.data[DOMAIN][entry.entry_id].update({
            "daily_coordinator": daily_coord,
            "monthly_coordinator": monthly_coord,
            "yearly_coordinator": yearly_coord,
            "total_coordinator": total_coord,
        })
        _LOGGER.info(f"Created total coordinator for {device_sn}")

        # Prime daily coordinator (non-blocking)
        hass.async_create_task(daily_coord.async_config_entry_first_refresh())
        hass.async_create_task(monthly_coord.async_config_entry_first_refresh())
        hass.async_create_task(yearly_coord.async_config_entry_first_refresh())
        hass.async_create_task(total_coord.async_config_entry_first_refresh())

        polling_interval = datetime.timedelta(seconds=DEFAULT_POLLING_INTERVAL)

        async def _async_poll_data(now=None):
            """Poll data from MQTT client."""
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("MQTT Poll %s.", device_sn)
            domain_data = hass.data.get(DOMAIN)
            if not domain_data:
                _LOGGER.warning("Lumentree domain data gone. Stop poll."); return
            entry_data = domain_data.get(entry.entry_id)
            if not entry_data:
                _LOGGER.warning(f"Entry data missing {entry.entry_id}. Stop poll.")
                nonlocal remove_interval
                current_timer = remove_interval
                if callable(current_timer):
                    try:
                        current_timer()
                        _LOGGER.info(f"MQTT poll timer cancelled {device_sn}."); remove_interval=None
                    except Exception as timer_err:
                        _LOGGER.error(f"Error cancel timer {device_sn}: {timer_err}")
                return

            active_mqtt_client = entry_data.get("mqtt_client")
            if not isinstance(active_mqtt_client, LumentreeMqttClient) or not active_mqtt_client.is_connected:
                _LOGGER.warning(f"MQTT {device_sn} not ready."); return
            try:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Requesting MQTT (main data) %s...", device_sn)
                await active_mqtt_client.async_request_data()
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT request sent %s.", device_sn)
            except Exception as poll_err:
                _LOGGER.error(f"MQTT poll error {device_sn}: {poll_err}")

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
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_mqtt))

        # Services: backfill_now, recompute_month_year, purge_cache, backfill_all, backfill_gaps,
        #            mark_empty_dates, mark_coverage_range
        async def _svc_backfill(call):
            days = int(call.data.get("days", 365))
            await aggregator.backfill_last_n_days(days)

        async def _svc_recompute(call):
            # Recompute aggregates for the current year
            now = datetime.datetime.now()
            c = cache_io.load_year(device_id, now.year)
            cache_io.recompute_aggregates(c)
            cache_io.save_year(device_id, now.year, c)

        async def _svc_purge(call):
            year = int(call.data.get("year", datetime.datetime.now().year))
            cache_io.purge_year(device_id, year)

        async def _svc_backfill_all(call):
            max_years = int(call.data.get("max_years", 10))
            empty_streak = int(call.data.get("empty_streak", 14))
            await aggregator.backfill_all(max_years=max_years, empty_streak=empty_streak)

        async def _svc_backfill_gaps(call):
            max_years = int(call.data.get("max_years", 3))
            max_days_per_run = int(call.data.get("max_days_per_run", 30))
            await aggregator.backfill_gaps(max_years=max_years, max_days_per_run=max_days_per_run)

        async def _svc_mark_empty_dates(call):
            year = int(call.data["year"])  # required
            dates = list(call.data.get("dates", []))
            c = cache_io.load_year(device_id, year)
            for ds in dates:
                c = cache_io.mark_empty(c, ds)
            cache_io.save_year(device_id, year, c)

        async def _svc_mark_coverage_range(call):
            year = int(call.data["year"])  # required
            earliest = call.data.get("earliest")
            latest = call.data.get("latest")
            c = cache_io.load_year(device_id, year)
            meta = c.setdefault("meta", {})
            cov = meta.setdefault("coverage", {"earliest": None, "latest": None})
            if earliest is not None:
                cov["earliest"] = earliest
            if latest is not None:
                cov["latest"] = latest
            cache_io.save_year(device_id, year, c)

        hass.services.async_register(DOMAIN, "backfill_now", _svc_backfill)
        hass.services.async_register(DOMAIN, "recompute_month_year", _svc_recompute)
        hass.services.async_register(DOMAIN, "purge_cache", _svc_purge)
        hass.services.async_register(DOMAIN, "backfill_all", _svc_backfill_all)
        hass.services.async_register(DOMAIN, "backfill_gaps", _svc_backfill_gaps)
        hass.services.async_register(DOMAIN, "mark_empty_dates", _svc_mark_empty_dates)
        hass.services.async_register(DOMAIN, "mark_coverage_range", _svc_mark_coverage_range)

        # Auto backfill: first-run (background) and nightly delta
        async def _first_run_backfill() -> None:
            try:
                _LOGGER.info("Auto backfill: starting FULL history (background)")
                await aggregator.backfill_all(max_years=10, empty_streak=14)
                _LOGGER.info("Auto backfill: completed FULL history")
            except Exception as err:
                _LOGGER.error(f"Auto backfill initial failed: {err}")

        async def _nightly_delta(now=None):
            try:
                today = datetime.date.today()
                yesterday = today - datetime.timedelta(days=1)
                _LOGGER.info("Nightly backfill: %s → %s", yesterday, today)
                await aggregator.backfill_days(yesterday, today)
                # Lấp các ngày còn thiếu dần dần (giới hạn để tránh quá tải)
                filled = await aggregator.backfill_gaps(max_years=3, max_days_per_run=30)
                if filled:
                    _LOGGER.info("Nightly gap fill: added %s missing days", filled)
            except Exception as err:
                _LOGGER.error(f"Nightly backfill error: {err}")

        # Kick off initial backfill without blocking setup
        hass.async_create_task(_first_run_backfill())

        # Schedule nightly job every 24h
        remove_nightly = async_track_time_interval(hass, _nightly_delta, datetime.timedelta(hours=24))
        hass.data[DOMAIN][entry.entry_id]["remove_nightly"] = remove_nightly

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info(f"Setup complete for {entry.title} (SN/ID: {device_sn})")
        return True

    except ConfigEntryNotReady as e:
        _LOGGER.warning(f"Setup failed {entry.title}: {e}. Cleaning up...")
        if isinstance(mqtt_client, LumentreeMqttClient):
            await mqtt_client.disconnect()
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    except Exception as final_exception:
        _LOGGER.exception(f"Unexpected setup error {entry.title}")
        if isinstance(mqtt_client, LumentreeMqttClient):
            await mqtt_client.disconnect()
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id, None)
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(f"Unloading Lumentree: {entry.title} (SN/ID: {entry.data.get(CONF_DEVICE_SN)})")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if entry_data:
        mqtt_client = entry_data.get("mqtt_client")
        if isinstance(mqtt_client, LumentreeMqttClient):
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Disconnecting MQTT %s.", entry.data.get(CONF_DEVICE_SN))
            hass.async_create_task(mqtt_client.disconnect())
        # Cancel nightly timer if any
        rm = entry_data.get("remove_nightly")
        if callable(rm):
            try:
                rm()
            except Exception:
                pass
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Removed entry data %s.", entry.entry_id)
    else:
        _LOGGER.warning(f"No entry data {entry.entry_id} to clean.")
    _LOGGER.info(f"Unload {entry.title}: {'OK' if unload_ok else 'Failed'}.")
    return unload_ok