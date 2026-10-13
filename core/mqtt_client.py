"""MQTT client for Lumentree integration."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from functools import partial
from typing import Any

import paho.mqtt.client as paho
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from paho.mqtt.client import MQTTMessage

from ..const import (
    DEFAULT_POLLING_INTERVAL,
    KEY_LAST_RAW_MQTT,
    KEY_ONLINE_STATUS,
    MQTT_BROKER,
    MQTT_CLIENT_ID_FORMAT,
    MQTT_KEEPALIVE,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_PUB_TOPIC_FORMAT,
    MQTT_SUB_TOPIC_FORMAT,
    MQTT_USERNAME,
    REG_ADDR_CELL_COUNT,
    REG_ADDR_CELL_START,
    SIGNAL_UPDATE_FORMAT,
)
from .realtime_parser import generate_modbus_read_command, parse_mqtt_payload

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_SECONDS = 5
MAX_RECONNECT_ATTEMPTS = 10
CONNECT_TIMEOUT = 20
OFFLINE_TIMEOUT_SECONDS = DEFAULT_POLLING_INTERVAL * 2.5
NUM_MAIN_REGISTERS_TO_READ = 151  # Read registers 0-150 (extended for work/battery mode)
BATCH_DELAY_SECONDS = 0.1  # Coalesce frames arriving together into one dispatch

# paho-mqtt 2.x deprecates the 1.x callback signatures and 3.0 removes them;
# 1.6 (what Home Assistant 2024.4 ships) has no CallbackAPIVersion at all.
_CALLBACK_API_VERSION2 = getattr(getattr(paho, "CallbackAPIVersion", None), "VERSION2", None)

_CONNACK_ERRORS = {
    1: "Protocol",
    2: "ID Rejected",
    3: "Server Unavailable",
    4: "Bad User/Password",
    5: "Not Authorized",
}


def _new_paho_client(client_id: str) -> paho.Client:
    """Build a paho client using the newest callback API the library offers."""
    if _CALLBACK_API_VERSION2 is not None:
        return paho.Client(_CALLBACK_API_VERSION2, client_id=client_id, protocol=paho.MQTTv311)
    return paho.Client(client_id=client_id, protocol=paho.MQTTv311)


def _stop_quietly(mqttc: paho.Client) -> None:
    """Disconnect a paho client and join its network thread (blocking).

    DISCONNECT goes out first, while the network loop is still running to
    send it; stopping the loop first left the broker to notice the drop only
    at keepalive expiry.  Either step failing is logged at debug and
    otherwise ignored: the client is being discarded, and a failed
    ``loop_stop()`` is worth seeing only because it leaks the paho thread.

    The callbacks are detached first.  A discarded client's ``on_disconnect``
    would otherwise schedule a reconnect of its own (one more on every failed
    hard reconnect) and flip ``_is_connected`` under a replacement client.
    """
    mqttc.on_connect = None
    mqttc.on_disconnect = None
    mqttc.on_message = None
    try:
        mqttc.disconnect()
    except Exception:
        _LOGGER.debug("MQTT disconnect() failed", exc_info=True)
    try:
        mqttc.loop_stop()
    except Exception:
        _LOGGER.debug("MQTT loop_stop() failed", exc_info=True)


def _describe_connack(rc: Any) -> str:
    """Human-readable CONNACK result for either callback API.

    API v1 hands over the raw MQTT 3.1.1 integer; API v2 a ``ReasonCode`` whose
    ``str()`` is already the reason's name.
    """
    if isinstance(rc, int):
        return _CONNACK_ERRORS.get(rc, "Unknown")
    return str(rc)


class LumentreeMqttClient:
    """Manages MQTT connection, messages, and online status with batch updates."""

    __slots__ = (
        "hass",
        "entry",
        "_device_sn",
        "_device_id",
        "_mqttc",
        "_client_id",
        "_signal_update",
        "_topic_sub",
        "_topic_pub",
        "_connect_lock",
        "_reconnect_attempts",
        "_is_connected",
        "_stopping",
        "_stopping_lock",
        "_connected_event",
        "_online",
        "_offline_timer_unsub",
        "_offline_timer_gen",
        "_batch_timer",
        "_pending_updates",
    )

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device_sn: str, device_id: str
    ) -> None:
        """Initialize the MQTT client with batch updates.

        Args:
            hass: Home Assistant instance
            entry: Config entry
            device_sn: Device serial number
            device_id: Device ID
        """
        self.hass = hass
        self.entry = entry
        self._device_sn = device_sn
        self._device_id = device_id
        self._mqttc: paho.Client | None = None

        timestamp = int(time.time())
        try:
            self._client_id = MQTT_CLIENT_ID_FORMAT.format(
                device_id=self._device_id, timestamp=timestamp
            )
        except KeyError:
            _LOGGER.error("Failed to format MQTT Client ID")
            self._client_id = f"ha-lumentree-{self._device_sn}-{timestamp}"

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("MQTT Client ID: %s", self._client_id)

        self._signal_update = SIGNAL_UPDATE_FORMAT.format(device_sn=self._device_sn)
        self._topic_sub = MQTT_SUB_TOPIC_FORMAT.format(device_sn=self._device_sn)
        self._topic_pub = MQTT_PUB_TOPIC_FORMAT.format(device_sn=self._device_sn)

        self._connect_lock = asyncio.Lock()
        self._reconnect_attempts = 0
        self._is_connected = False
        self._stopping = False
        self._stopping_lock = threading.Lock()
        self._connected_event = asyncio.Event()
        self._online: bool = False
        self._offline_timer_unsub: Callable | None = None
        self._offline_timer_gen: int = 0

        # Batch update optimization
        self._batch_timer: asyncio.TimerHandle | None = None
        self._pending_updates: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        """Check if MQTT is connected."""
        return self._is_connected

    def _cancel_offline_timer(self) -> None:
        """Cancel the offline timer if active.

        Event-loop-only: the TimerHandle's unsubscribe is not thread-safe, so
        a call arriving off-loop is deferred onto the loop instead of reaching
        the handle directly.
        """
        if not self._is_on_event_loop():
            self._call_soon(self._cancel_offline_timer)
            return
        if self._offline_timer_unsub:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Cancelling offline timer %s", self._client_id)
            try:
                self._offline_timer_unsub()
            except Exception as exc:
                _LOGGER.warning(f"Error cancelling timer {self._client_id}: {exc}")
            self._offline_timer_unsub = None

    def _cancel_batch_timer(self) -> None:
        """Cancel the batch timer, flushing whatever it was holding.

        Event-loop-only, like every other touch of ``_batch_timer``.
        """
        if self._batch_timer is not None:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Cancelling batch timer %s", self._client_id)
            self._batch_timer.cancel()
            self._batch_timer = None
        self._flush_pending_updates()

    def _flush_pending_updates(self) -> None:
        """Dispatch every queued update as one batch (event loop only)."""
        self._batch_timer = None
        if not self._pending_updates:
            return
        batch = self._pending_updates
        self._pending_updates = {}
        async_dispatcher_send(self.hass, self._signal_update, batch)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Sent batch update for %s", self._device_sn)

    def _queue_update(self, data: dict[str, Any]) -> None:
        """Add update to queue for batch processing.

        The first update arms a single ``call_later`` handle and later ones
        just merge into the pending dict, so a burst of frames (main block and
        battery cells) becomes one dispatch.  The handle is set synchronously:
        the earlier task-based timer was armed one loop iteration late, so two
        frames in the same iteration each started a timer and the second
        cancelled the first.

        Args:
            data: Update data to queue
        """
        if not self._is_on_event_loop():
            self._call_soon(self._queue_update, data)
            return
        self._pending_updates.update(data)
        if self._batch_timer is None:
            self._batch_timer = self.hass.loop.call_later(
                BATCH_DELAY_SECONDS, self._flush_pending_updates
            )

    def _is_on_event_loop(self) -> bool:
        """Return True when running on this instance's event loop thread."""
        try:
            return asyncio.get_running_loop() is self.hass.loop
        except RuntimeError:  # No running loop at all -> not the loop thread
            return False

    def _call_soon(self, func: Callable, *args) -> None:
        """Marshal ``func`` onto the event loop unless we are already there.

        The paho callbacks and Home Assistant's executor-run timer targets can
        fire from any thread; the APIs they reach for (the dispatcher, the
        offline-timer unsubscribe) are event-loop-only.
        """
        if self._is_on_event_loop():
            func(*args)
        else:
            self.hass.loop.call_soon_threadsafe(func, *args)

    def _set_offline(self, gen: int = -1, *args) -> None:
        """Set status to offline and dispatch update.

        Safe to call from any thread.  _on_disconnect runs on the paho network
        thread, and Home Assistant runs a bare ``lambda`` handed to
        ``async_call_later`` in an executor thread -- only a ``@callback``
        target stays on the loop.  Both the dispatcher call and the
        offline-timer unsubscribe below are event-loop-only APIs, so a call
        arriving off-loop is marshalled onto the loop first.

        Args:
            gen: Timer generation. Only applies if gen matches _offline_timer_gen
                 (prevents stale timer callbacks from cancelling fresh timers).
        """
        if not self._is_on_event_loop():
            self.hass.loop.call_soon_threadsafe(self._set_offline, gen)
            return
        if gen >= 0 and gen != self._offline_timer_gen:
            return  # Stale timer callback, ignore
        _LOGGER.info("MQTT data timeout or disconnect %s. Setting offline.", self._client_id)
        self._cancel_offline_timer()
        if self._online:
            self._online = False
            async_dispatcher_send(self.hass, self._signal_update, {KEY_ONLINE_STATUS: False})

    def _start_offline_timer(self) -> None:
        """Start or restart the offline timer.

        Event-loop-only: ``async_call_later`` and the handle it returns are not
        thread-safe, so a call arriving off-loop is deferred onto the loop.
        """
        if not self._is_on_event_loop():
            self._call_soon(self._start_offline_timer)
            return
        self._cancel_offline_timer()
        self._offline_timer_gen += 1
        gen = self._offline_timer_gen
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Starting offline timer (%ss, gen=%s) for %s",
                OFFLINE_TIMEOUT_SECONDS,
                gen,
                self._client_id,
            )
        self._offline_timer_unsub = async_call_later(
            self.hass, OFFLINE_TIMEOUT_SECONDS, lambda _now: self._set_offline(gen)
        )

    async def connect(self) -> None:
        """Establish MQTT connection."""
        async with self._connect_lock:
            if self._is_connected:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("MQTT already connected for %s", self._device_sn)
                return

            self._stopping = False
            self._connected_event.clear()
            mqttc = _new_paho_client(self._client_id)
            mqttc.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
            mqttc.on_connect = self._on_connect
            mqttc.on_disconnect = self._on_disconnect
            mqttc.on_message = self._on_message
            self._mqttc = mqttc

            _LOGGER.info(
                "MQTT connecting: %s:%s (Client: %s) for SN: %s",
                MQTT_BROKER,
                MQTT_PORT,
                self._client_id,
                self._device_sn,
            )

            try:
                await self.hass.async_add_executor_job(
                    mqttc.connect, MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE
                )
                mqttc.loop_start()
                _LOGGER.info(
                    "MQTT loop started %s. Waiting for CONNACK (%ss)",
                    self._client_id,
                    CONNECT_TIMEOUT,
                )

                try:
                    await asyncio.wait_for(self._connected_event.wait(), timeout=CONNECT_TIMEOUT)
                except TimeoutError as err:
                    # Cleanup happens in the handler below.  This used to call
                    # self.disconnect(), which takes _connect_lock -- the lock
                    # this method is still holding -- so a missing CONNACK hung
                    # setup (and every later hard reconnect) forever.
                    raise ConnectionRefusedError("MQTT connection timeout") from err
                if not self._is_connected:
                    raise ConnectionRefusedError("MQTT connection refused")
                _LOGGER.info("MQTT connected successfully %s", self._client_id)
            except Exception as exc:
                _LOGGER.error("Failed MQTT connect %s: %s", self._client_id, exc)
                self._mqttc = None
                self._is_connected = False
                self._connected_event.set()
                # loop_stop() joins the network thread, so it must not run on
                # the event loop.
                try:
                    await self.hass.async_add_executor_job(_stop_quietly, mqttc)
                except Exception as stop_exc:
                    _LOGGER.warning("Loop stop error: %s", stop_exc)
                if isinstance(exc, ConnectionRefusedError):
                    raise
                raise ConnectionRefusedError(f"MQTT setup error: {exc}") from exc

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Callback when connection is established.

        Args:
            client: MQTT client instance
            userdata: User data
            flags: Connection flags
            rc: Connection result code
            properties: Connection properties (MQTT v5)
        """
        if rc == paho.CONNACK_ACCEPTED:
            _LOGGER.info(
                "MQTT connected (rc=%s) %s. Subscribing to: %s",
                rc,
                self._client_id,
                self._topic_sub,
            )
            self._reconnect_attempts = 0
            try:
                result, mid = client.subscribe(self._topic_sub, 0)
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Subscribe %s %s (mid=%s)",
                        "OK" if result == 0 else "Failed",
                        self._topic_sub,
                        mid,
                    )
                self._is_connected = True
            except Exception as exc:
                _LOGGER.error("MQTT subscribe failed %s: %s", self._client_id, exc)
                self._is_connected = False
                self._call_soon(self._connected_event.set)
                self._call_soon(self._set_offline)
                self._call_soon(self._safe_schedule_reconnect)
                return
            self._call_soon(self._connected_event.set)
        else:
            _LOGGER.error(
                "MQTT connection refused %s (rc=%s): %s",
                self._client_id,
                rc,
                _describe_connack(rc),
            )
            self._is_connected = False
            self._call_soon(self._connected_event.set)
            self._call_soon(self._set_offline)
            self._call_soon(self._safe_schedule_reconnect)

    def _on_disconnect(self, client, userdata, *args) -> None:
        """Callback when disconnected.

        paho's callback API v1 passes ``(rc)`` or ``(rc, properties)``; v2
        passes ``(disconnect_flags, reason_code, properties)``.  Either way the
        result code is the last argument that is not properties.

        Args:
            client: MQTT client instance
            userdata: User data
            args: Callback-API-specific tail, see above
        """
        rc = args[1] if len(args) >= 3 else (args[0] if args else 0)
        self._is_connected = False
        # _set_offline cancels the offline timer itself, on the event loop.
        # Cancelling it here as well would touch the TimerHandle from the paho
        # thread, which is not thread-safe.
        self._set_offline()

        if rc == 0:
            _LOGGER.info(f"MQTT disconnected cleanly {self._client_id}")
        else:
            _LOGGER.warning(f"MQTT unexpected disconnect {self._client_id} (rc={rc})")

        self._call_soon(self._safe_schedule_reconnect)

    @callback
    def _safe_schedule_reconnect(self) -> None:
        """Thread-safe check before scheduling reconnect.

        Called via call_soon_threadsafe from paho callbacks to ensure
        _stopping check runs on the event loop thread, preventing the
        zombie-reconnect race where disconnect() sets _stopping=True
        while a paho callback reads a stale False.
        """
        if not self._stopping:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule an asynchronous reconnection attempt with exponential backoff.

        After MAX_RECONNECT_ATTEMPTS soft reconnect failures, switches to hard reconnect
        (fresh paho client). Never gives up permanently — MQTT is the primary data source.
        """
        self._reconnect_attempts += 1

        if self._reconnect_attempts <= MAX_RECONNECT_ATTEMPTS:
            delay = min(RECONNECT_DELAY_SECONDS * (2 ** (self._reconnect_attempts - 1)), 60)
            _LOGGER.info(
                "Scheduling MQTT soft reconnect %s/%s for %s in %ss",
                self._reconnect_attempts,
                MAX_RECONNECT_ATTEMPTS,
                self._client_id,
                delay,
            )
        else:
            delay = 120
            _LOGGER.warning(
                "MQTT soft reconnects exhausted (%sx) for %s. "
                "Will attempt hard reconnect (fresh connection) in %ss",
                MAX_RECONNECT_ATTEMPTS,
                self._client_id,
                delay,
            )

        self._call_soon(lambda: self.hass.async_create_task(self._async_reconnect(delay)))

    async def _async_reconnect(self, delay: float) -> None:
        """Wait for delay and attempt reconnection.

        Uses soft reconnect (reuse existing client) for first MAX_RECONNECT_ATTEMPTS,
        then switches to hard reconnect (fresh paho client) for subsequent attempts.

        Args:
            delay: Delay in seconds before reconnecting
        """
        await asyncio.sleep(delay)
        if self._stopping:
            return

        if self._reconnect_attempts <= MAX_RECONNECT_ATTEMPTS:
            # Soft reconnect: reuse existing paho client
            if not self.is_connected and self._mqttc:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Attempting MQTT soft reconnect %s", self._client_id)
                try:
                    await self.hass.async_add_executor_job(self._mqttc.reconnect)
                except Exception as exc:
                    _LOGGER.warning("MQTT soft reconnect failed %s: %s", self._client_id, exc)
        else:
            # Hard reconnect: create a fresh paho client
            await self._hard_reconnect()

    async def _hard_reconnect(self) -> None:
        """Perform a hard reconnect by creating a fresh paho client.

        Stops and disconnects the old client, then calls connect() which creates
        a brand new MQTT connection. This recovers from cases where the old paho
        client is in a permanently broken state that soft reconnect can't fix.
        """
        _LOGGER.info("MQTT hard reconnect: creating fresh connection %s", self._client_id)

        # Clean up old client
        old_mqttc = self._mqttc
        self._mqttc = None
        self._cancel_batch_timer()

        if old_mqttc:
            # Off the event loop: loop_stop() joins the paho network thread.
            await self.hass.async_add_executor_job(_stop_quietly, old_mqttc)

        self._is_connected = False
        self._connected_event.clear()
        self._reconnect_attempts = 0

        try:
            await self.connect()
            _LOGGER.info("MQTT hard reconnect successful %s", self._client_id)
        except Exception as exc:
            _LOGGER.error("MQTT hard reconnect failed %s: %s", self._client_id, exc)
            # An unload that landed while connect() was in flight has set
            # _stopping; rescheduling then would reconnect a removed entry.
            if self._stopping:
                return
            self._reconnect_attempts = MAX_RECONNECT_ATTEMPTS
            self._schedule_reconnect()

    def _on_message(self, client, userdata, msg: MQTTMessage) -> None:
        """Callback when a message is received.

        Args:
            client: MQTT client instance
            userdata: User data
            msg: MQTT message
        """
        topic = msg.topic
        try:
            payload_bytes = msg.payload
            payload_hex = bytes(payload_bytes).hex() if payload_bytes else ""

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "MQTT message received %s: topic='%s', payload='%s...' (len: %s)",
                    self._client_id,
                    topic,
                    payload_hex[:60],
                    len(payload_bytes),
                )

            if topic == self._topic_sub:
                parsed_data = parse_mqtt_payload(payload_hex)
                if parsed_data:
                    if _LOGGER.isEnabledFor(logging.DEBUG):
                        _LOGGER.debug("Parsed data %s: %s", self._client_id, parsed_data)

                    # Update online status and reset timer.  _start_offline_timer
                    # touches the TimerHandle and async_call_later, neither of
                    # which is thread-safe, so it is marshalled onto the loop.
                    if not self._online:
                        self._online = True
                        parsed_data[KEY_ONLINE_STATUS] = True
                    self._call_soon(self._start_offline_timer)

                    # Add raw hex data
                    parsed_data[KEY_LAST_RAW_MQTT] = payload_hex

                    # Use batch update instead of immediate dispatch
                    self._call_soon(self._queue_update, parsed_data)
            else:
                _LOGGER.warning(f"Unexpected topic {self._client_id}: {topic}")
        except Exception:
            _LOGGER.exception(f"Error processing MQTT message {topic} {self._client_id}")

    async def _publish_command(self, command_hex: str) -> bool:
        """Internal helper to publish a hex command.

        Args:
            command_hex: Hex string command to publish

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected or not self._mqttc:
            _LOGGER.error(f"MQTT not connected {self._client_id}, cannot publish")
            return False

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Publishing to %s (%s): %s", self._topic_pub, self._client_id, command_hex
            )

        try:
            payload_bytes = bytes.fromhex(command_hex)
            publish_task = partial(
                self._mqttc.publish, self._topic_pub, payload=payload_bytes, qos=0
            )
            msg_info = await self.hass.async_add_executor_job(publish_task)

            if msg_info is None or msg_info.rc != paho.MQTT_ERR_SUCCESS:
                _LOGGER.error(
                    f"MQTT publish failed {self._client_id} RC: {msg_info.rc if msg_info else 'Executor Error'}"
                )
                return False
            else:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Publish OK (mid=%s) %s", msg_info.mid, self._client_id)
                return True
        except ValueError as exc:
            _LOGGER.error(f"Invalid hex payload {self._client_id}: {exc}")
            return False
        except Exception as exc:
            _LOGGER.error(f"Failed MQTT publish {self._client_id}: {exc}")
            return False

    async def async_request_data(self) -> None:
        """Request the main device data (registers 0-150)."""
        start_address = 0
        num_registers = NUM_MAIN_REGISTERS_TO_READ
        slave_id = 1
        func_code = 3

        command_hex = generate_modbus_read_command(
            slave_id, func_code, start_address, num_registers
        )
        if command_hex:
            await self._publish_command(command_hex)
        else:
            _LOGGER.error(
                "Failed to generate Modbus read (0-%s) %s",
                num_registers - 1,
                self._client_id,
            )

    async def async_request_battery_cells(self) -> None:
        """Request the battery cell data."""
        start = REG_ADDR_CELL_START
        count = REG_ADDR_CELL_COUNT
        sid = 1
        fc = 3

        command_hex = generate_modbus_read_command(sid, fc, start, count)
        if command_hex:
            await self._publish_command(command_hex)
        else:
            _LOGGER.error(
                f"Failed to generate Modbus read ({start}-{start + count - 1}) {self._client_id}"
            )

    async def disconnect(self) -> None:
        """Disconnect the MQTT client and clean up timers."""
        _LOGGER.info(f"Disconnecting MQTT {self._client_id}")
        self._stopping = True
        self._reconnect_attempts = MAX_RECONNECT_ATTEMPTS
        self._connected_event.set()

        # Cancel all timers
        self._cancel_offline_timer()
        self._cancel_batch_timer()
        self._set_offline()

        mqttc_to_disconnect = None
        async with self._connect_lock:
            if self._mqttc:
                mqttc_to_disconnect = self._mqttc
                self._mqttc = None
            self._is_connected = False

        if mqttc_to_disconnect:
            # The session is clean, so the broker drops the subscription with
            # the connection; there is nothing to unsubscribe first.
            try:
                await self.hass.async_add_executor_job(_stop_quietly, mqttc_to_disconnect)
                _LOGGER.info("MQTT client disconnected %s", self._client_id)
            except Exception as exc:
                _LOGGER.warning("Error during MQTT disconnect %s: %s", self._client_id, exc)
        else:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("MQTT client already None %s", self._client_id)
