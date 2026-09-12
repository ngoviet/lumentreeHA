"""End-to-end: a real MQTT frame becomes Home Assistant entity state.

This test drives the whole real-time path with real Home Assistant objects:
``hass.config_entries.async_setup(entry)`` runs the shipping
``__init__.async_setup_entry``, which builds the real API client, the real MQTT
client and the real sensor entities. Only two things are faked, both at a
process boundary:

* the HTTP server, via HA's own ``aioclient_mock`` -- the vendor is never
  contacted;
* the MQTT socket, by replacing ``connect`` on the client -- the broker is never
  contacted. The client's ``__init__``, its ``disconnect``, and its entire
  message path (``_on_message`` -> parse -> dispatch) are the real code.

That is the point of this file. The unit tests stop at module boundaries, and
what silently breaks is the wiring *between* the modules: an entity key that
drifts, a dispatcher signal built from two different format strings, a ``const``
key that gets renamed. None of those are visible to a per-module test.

The frames are built by ``build_frame`` below, a copy of the helper in
``test_realtime_parser.py``: a real Modbus-RTU 0x03 response with a valid CRC
over the same register layout the device publishes. A captured dump would be
truer to life, but the only recording in the tree (``mqtt_discovery.json``) has
had its non-ASCII bytes flattened to U+FFFD, so every frame in it fails CRC.
Building the frame keeps this file honest about what it is feeding in.

Skipped unless Home Assistant is installed. ``pytest tests/`` on a bare
interpreter (CI installs pytest + aiohttp + paho + crcmod only) still collects
and passes the rest of the suite.
"""

from __future__ import annotations

import asyncio
import re

import pytest

try:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    HA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without Home Assistant
    HA_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not HA_AVAILABLE, reason="homeassistant is not installed; the e2e path needs it"
)

DEVICE_SN = "P250812039"

# Same wire format the device uses: a "++++" separator, then a 0x03 response.
SEPARATOR = "2b2b2b2b"


def _crc16(data: bytes) -> int:
    """Modbus CRC16, little-endian on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(registers: dict[int, int], n_regs: int = 151) -> str:
    """Build a CRC-valid 0x03 response carrying the given register values.

    151 registers is the full frame the device sends; the byte-count field is a
    single byte on the wire, so its 302-byte body declares 46.
    """
    body = bytearray()
    for i in range(n_regs):
        body += (registers.get(i, 0) & 0xFFFF).to_bytes(2, "big")
    pdu = bytes([0x01, 0x03, len(body) & 0xFF]) + bytes(body)
    return SEPARATOR + (pdu + _crc16(pdu).to_bytes(2, "little")).hex()


# A full frame with one value pinned, so an assertion has something exact to
# compare against without hardcoding the whole register map here.
FRAME_FULL = build_frame({50: 77})  # register 50 = BATTERY_SOC
BAD_CRC_FRAME = (SEPARATOR + "01030000ffff")

DEVICE_INFO = {
    "deviceId": DEVICE_SN,
    "deviceSn": DEVICE_SN,
    "deviceType": "SUNT-6.0kW-HT",
    "controllerVersion": "1.0.0",
}

# ``deviceManage`` answers ``data.devices[0]``, not ``data`` itself -- reflected
# here because ``async_setup_entry`` aborts with "Device not found" otherwise.
DEVICE_MANAGE = {"returnValue": 1, "data": {"devices": [DEVICE_INFO]}}

# The vendor answers every read endpoint with this envelope. Returning it for
# anything unregistered keeps a coordinator refresh from raising mid-setup; the
# value under test comes from the MQTT frame, not from HTTP.
EMPTY_OK = {"returnValue": 1, "data": {}}


@pytest.fixture
def lumentree_integration(hass: HomeAssistant):
    """Make Home Assistant able to find this integration.

    The repository root *is* the ``lumentree`` package (``hacs.json`` sets
    ``content_in_root: true``), so there is no ``custom_components/lumentree``
    directory for HA's loader to scan: ``Integration.resolve_from_root`` looks
    for ``custom_components/lumentree/manifest.json`` and finds nothing.

    So the ``Integration`` is built here from the real ``manifest.json`` and the
    real repository root, and registered in HA's integration cache under the
    domain. The component itself is *not* faked -- ``pkg_path`` is the name
    ``conftest`` already registered in ``sys.modules``, so
    ``Integration.get_component()`` imports the shipping ``__init__.py``.

    Every field HA would have derived is read from the manifest rather than
    hardcoded, so a manifest that stops being loadable fails here.
    """
    import json
    import pathlib

    import custom_components.lumentree as package
    from homeassistant import loader

    root = pathlib.Path(__file__).resolve().parent.parent

    # ``conftest`` registers ``custom_components.lumentree`` as an empty
    # namespace package so the unit tests can import submodules without running
    # the integration's entry point. HA's loader caches components by module
    # object, so the real ``__init__.py`` has to be executed into *that* module
    # before the loader asks for it -- otherwise setup finds an empty module
    # with no ``async_setup_entry``.
    init_py = root / "__init__.py"
    exec(compile(init_py.read_text(encoding="utf-8"), str(init_py), "exec"), package.__dict__)

    assert hasattr(package, "async_setup_entry"), (
        "__init__.py did not define async_setup_entry after being executed"
    )

    # Setup waits ten seconds between warming the daily coordinator and the
    # stats coordinators, so a real backfill can land. Nothing here is about
    # that gap, and ten seconds times every test is the whole runtime, so run it
    # as fast as the scheduler allows.
    package._STAGGER_DELAY_SECONDS = 0.01

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "lumentree", "manifest domain drifted"

    integration = loader.Integration(
        hass,
        pkg_path="custom_components.lumentree",
        file_path=root,
        manifest=manifest,
        top_level_files={entry.name for entry in root.iterdir()},
    )
    hass.data.setdefault(loader.DATA_INTEGRATIONS, {})["lumentree"] = integration
    yield integration
    hass.data.get(loader.DATA_INTEGRATIONS, {}).pop("lumentree", None)


@pytest.fixture
def vendor_http(aioclient_mock):
    """Intercept the vendor's HTTP API.

    ``aioclient_mock`` is Home Assistant's own aiohttp mocker: it replaces
    ``_async_create_clientsession``, so it catches the session the integration
    asks HA for. Any route not registered here raises ``AssertionError`` from
    the mocker, so a forgotten call fails the test instead of reaching the
    internet.
    """
    # ``aioclient_mock``'s response object exposes ``.status`` but not
    # ``response.ok``, which is the aiohttp property ``api_client._request``
    # reads. Deriving it here keeps the shim at the mock boundary instead of
    # changing shipping code to accommodate a test double.
    def _with_ok(response):
        response.ok = response.status < 400
        return response

    _original_match = aioclient_mock.match_request

    async def _match(method, url, **kwargs):
        return _with_ok(await _original_match(method, url, **kwargs))

    aioclient_mock.match_request = _match

    # ``deviceManage`` is a POST with the SN in the query string -- asserted
    # here because it is a vendor contract, not a choice this repo controls.
    aioclient_mock.post(
        re.compile(r"http://lesvr\.suntcn\.com/lesvr/deviceManage.*"),
        json=DEVICE_MANAGE,
    )
    # Coordinator refreshes run during setup and hit other endpoints. They are
    # not what this file tests, but an unanswered call aborts setup, so answer
    # them with an empty success rather than letting them fail.
    for method in ("get", "post"):
        getattr(aioclient_mock, method)(
            re.compile(r"http://lesvr\.suntcn\.com/.*"),
            json=EMPTY_OK,
        )
    return aioclient_mock


@pytest.fixture
async def entry(hass: HomeAssistant, lumentree_integration):
    """Config entry shaped exactly like the one the config flow produces."""
    entry = MockConfigEntry(
        domain="lumentree",
        title="Test Inverter",
        unique_id=DEVICE_SN,
        data={
            "device_sn": DEVICE_SN,
            "device_id": DEVICE_SN,
            "http_token": "test-token",
        },
    )
    entry.add_to_hass(hass)
    yield entry

    # Setup arms a 5s poll timer and a nightly timer. HA's ``verify_cleanup``
    # fixture fails the test if either is still pending at teardown, so unload
    # the entry the same way a user removing it would. Doing it here rather than
    # in each test also means every test exercises the real unload path.
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry, mqtt: FakeTransport, monkeypatch) -> dict:
    """Run the integration's real setup and return the entities by sensor key."""
    from custom_components.lumentree.const import DOMAIN
    from custom_components.lumentree.core import mqtt_client as mqtt_module

    # Replace the transport only. ``disconnect`` is deliberately left real: it
    # is the code that cancels the offline timer, and stubbing it out leaks a
    # 12.5s ``async_call_later`` into teardown. With no ``_mqttc`` (because
    # ``connect`` never built one) its body is just the cancel calls and a log
    # line, so running it is both safe and the point of the exercise.
    monkeypatch.setattr(mqtt_module.LumentreeMqttClient, "connect", mqtt.connect)
    monkeypatch.setattr(mqtt_module.LumentreeMqttClient, "async_request_data", mqtt.noop)
    monkeypatch.setattr(
        mqtt_module.LumentreeMqttClient, "async_request_battery_cells", mqtt.noop
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN], "setup left no state"
    client = hass.data[DOMAIN][entry.entry_id].get("mqtt_client")
    assert client is not None, "entry state carries no MQTT client"

    # Read the entities back through the registry so the assertions are about
    # what Home Assistant actually holds, not a list this test kept itself.
    #
    # Two maps come back. ``entities`` holds only entities with live state, and
    # is what the state assertions index into. ``all_keys`` holds every key the
    # integration registers, including the ones it ships disabled: HA registers
    # those but deliberately creates no state until a user enables them, so the
    # drift check must still count them as "has an entity".
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entities: dict[str, str] = {}
    all_keys: set[str] = set()
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        key = reg_entry.unique_id.removeprefix(f"{DEVICE_SN}_")
        all_keys.add(key)
        if reg_entry.disabled_by is not None:
            continue
        state = hass.states.get(reg_entry.entity_id)
        assert state is not None, f"{reg_entry.entity_id} is registered but has no state"
        entities[key] = reg_entry.entity_id
    assert entities, "setup registered no sensor entities"
    return {"client": client, "entities": entities, "all_keys": all_keys}


class FakeTransport:
    """Stands in for the MQTT socket; the message path stays real.

    Only ``connect`` is stubbed. The real ``disconnect`` is what cancels the
    client's timers, so it runs -- see ``_setup``.
    """

    async def connect(self) -> None:
        return None

    async def noop(self, *args, **kwargs) -> None:
        return None


def _deliver(client, payload_hex: str, topic: str | None = None) -> None:
    """Invoke the client's paho message handler with a constructed frame.

    The first two arguments are paho's client and userdata, which
    ``_on_message`` never reads; only ``msg.topic`` and ``msg.payload`` matter.
    """
    msg = type("Msg", (), {"topic": topic or client._topic_sub, "payload": bytes.fromhex(payload_hex)})
    client._on_message(None, None, msg)


async def _settle(hass: HomeAssistant, client) -> None:
    """Wait for a delivered frame to reach entity state.

    The client does not dispatch inline: ``_queue_update`` coalesces into a
    100ms ``asyncio.create_task`` so a burst of frames becomes one update.
    ``async_block_till_done`` does not wait for that task -- HA never tracked it
    -- so the sleep here is the wait, and the block afterwards drains the
    dispatcher callbacks it schedules.
    """
    await asyncio.sleep(0.15)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str):
    """Return a live state, failing the test rather than typing around it."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state"
    return state


async def test_constructed_frame_reaches_entity_state(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """A constructed frame ends up as decoded numbers on the entity states."""
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)

    _deliver(ctx["client"], FRAME_FULL)
    await _settle(hass, ctx["client"])

    from custom_components.lumentree.core.realtime_parser import parse_mqtt_payload

    expected = parse_mqtt_payload(FRAME_FULL)
    assert expected, "the constructed frame did not parse; the builder or the parser changed"

    soc = _state(hass, ctx["entities"]["battery_soc"])
    assert soc.state not in ("unknown", "unavailable"), (
        f"battery_soc stayed {soc.state!r}; the frame never reached the entity"
    )
    assert float(soc.state) == pytest.approx(float(expected["battery_soc"]))


async def test_every_parsed_key_has_an_entity(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """Each value the parser produces is consumed by a real entity.

    This is the drift check: a new key in the parser with no matching entity
    description, or a renamed one, is invisible to a per-module test and to a
    user until a value silently never updates.
    """
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)

    from custom_components.lumentree.const import KEY_LAST_RAW_MQTT
    from custom_components.lumentree.core.realtime_parser import parse_mqtt_payload

    parsed = parse_mqtt_payload(FRAME_FULL)
    assert parsed

    # The client injects these two itself; they are not parser outputs.
    client_injected = {"online_status", KEY_LAST_RAW_MQTT}
    orphaned = set(parsed) - ctx["all_keys"] - client_injected
    assert not orphaned, (
        f"parser produced keys with no entity: {sorted(orphaned)}. "
        "Add a description or stop emitting the key."
    )


async def test_dispatcher_signal_matches_between_client_and_sensor(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """The client's signal and the entities' subscription are one string.

    Both are built from ``SIGNAL_UPDATE_FORMAT`` in different modules. If either
    format string drifts, every sensor silently stops updating while the
    integration still looks healthy -- so pin the round trip.
    """
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)

    from homeassistant.helpers.dispatcher import async_dispatcher_send

    async_dispatcher_send(hass, ctx["client"]._signal_update, {"battery_soc": 77})
    await hass.async_block_till_done()

    soc = _state(hass, ctx["entities"]["battery_soc"])
    assert float(soc.state) == pytest.approx(77.0), (
        "entity ignored the client's dispatcher signal "
        f"({ctx['client']._signal_update!r}); the two formats have drifted"
    )


async def test_malformed_frame_leaves_previous_state_intact(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """Garbage on the topic must not blank out entity state."""
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)

    _deliver(ctx["client"], FRAME_FULL)
    await _settle(hass, ctx["client"])
    before = _state(hass, ctx["entities"]["battery_soc"]).state
    assert before not in ("unknown", "unavailable")

    # Bad CRC: the parser rejects the frame, so nothing is dispatched.
    _deliver(ctx["client"], BAD_CRC_FRAME)
    await _settle(hass, ctx["client"])

    assert _state(hass, ctx["entities"]["battery_soc"]).state == before


async def test_unexpected_topic_is_ignored(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """A message on a topic the client does not own changes nothing."""
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)
    before = _state(hass, ctx["entities"]["battery_soc"]).state

    _deliver(ctx["client"], FRAME_FULL, topic="reportApp/SOMEONE_ELSE")
    await _settle(hass, ctx["client"])

    assert _state(hass, ctx["entities"]["battery_soc"]).state == before


async def test_frame_marks_the_device_online(hass: HomeAssistant, entry, vendor_http, monkeypatch):
    """The first good frame flips online_status, which has no register of its own."""
    ctx = await _setup(hass, entry, FakeTransport(), monkeypatch)
    assert "online_status" in ctx["entities"]

    before = _state(hass, ctx["entities"]["online_status"]).state
    _deliver(ctx["client"], FRAME_FULL)
    await _settle(hass, ctx["client"])

    after = _state(hass, ctx["entities"]["online_status"]).state
    assert after == "on", (
        f"online_status did not react to a frame (before={before!r}, after={after!r})"
    )
