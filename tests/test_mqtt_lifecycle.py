"""Connection-lifecycle regression tests for the MQTT client.

* A broker that accepted the TCP connection but never sent CONNACK hung
  ``connect()`` forever: the timeout path called ``disconnect()``, which waits
  for the ``_connect_lock`` that ``connect()`` was still holding.  Setup never
  returned, and a hard reconnect that hit it stopped reconnecting for good.
* paho-mqtt 2.x calls ``on_disconnect`` with a different signature from 1.x.
* Two frames in one loop iteration started two batch timers, the second
  cancelling the first.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Any

import pytest


@pytest.fixture(scope="session")
def mqtt_module():
    from custom_components.lumentree.core import mqtt_client

    return mqtt_client


class _LoopHass:
    """The slice of hass the client touches, bound to the running loop."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()

    async def async_add_executor_job(self, func, *args):
        return await self.loop.run_in_executor(None, func, *args)

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


class _SilentBroker:
    """A paho client whose broker never answers CONNECT."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.on_connect: Any = None
        self.on_disconnect: Any = None
        self.on_message: Any = None

    def username_pw_set(self, **kwargs: Any) -> None:
        self.calls.append("username_pw_set")

    def connect(self, *args: Any) -> int:
        self.calls.append("connect")
        return 0

    def loop_start(self) -> None:
        self.calls.append("loop_start")

    def disconnect(self) -> None:
        self.calls.append("disconnect")

    def loop_stop(self) -> None:
        self.calls.append("loop_stop")


async def test_connack_timeout_raises_instead_of_deadlocking(mqtt_module, monkeypatch):
    broker = _SilentBroker()
    monkeypatch.setattr(mqtt_module, "_new_paho_client", lambda client_id: broker)
    monkeypatch.setattr(mqtt_module, "CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(mqtt_module, "async_dispatcher_send", lambda *a, **k: None)
    client = mqtt_module.LumentreeMqttClient(_LoopHass(), None, "SN1", "SN1")

    with pytest.raises(ConnectionRefusedError, match="timeout"):
        await asyncio.wait_for(client.connect(), timeout=5)

    assert not client.is_connected
    assert client._mqttc is None
    # DISCONNECT before the loop stops, and the discarded client can no longer
    # call back into this one.
    assert broker.calls[-2:] == ["disconnect", "loop_stop"]
    assert broker.on_disconnect is None and broker.on_connect is None
    # The lock is free again: a deadlock would make this wait forever.
    await asyncio.wait_for(client.disconnect(), timeout=5)


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param((7,), id="paho-1.x"),
        pytest.param((7, None), id="paho-1.x-mqttv5"),
        pytest.param(("flags", 7, None), id="paho-2.x"),
    ],
)
async def test_on_disconnect_accepts_both_callback_apis(mqtt_module, monkeypatch, tail):
    monkeypatch.setattr(mqtt_module, "async_dispatcher_send", lambda *a, **k: None)
    client = mqtt_module.LumentreeMqttClient(_LoopHass(), None, "SN1", "SN1")
    client._stopping = True  # keep the reconnect machinery out of the picture
    client._is_connected = True

    client._on_disconnect(None, None, *tail)
    await asyncio.sleep(0)

    assert not client.is_connected


def test_client_uses_the_current_paho_callback_api(mqtt_module):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        mqtt_module._new_paho_client("test-client")


async def test_frames_in_one_iteration_dispatch_once(mqtt_module, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        mqtt_module, "async_dispatcher_send", lambda _h, _s, data: sent.append(data)
    )
    monkeypatch.setattr(mqtt_module, "BATCH_DELAY_SECONDS", 0.01)
    client = mqtt_module.LumentreeMqttClient(_LoopHass(), None, "SN1", "SN1")

    client._queue_update({"a": 1})
    client._queue_update({"b": 2})
    await asyncio.sleep(0.05)

    assert sent == [{"a": 1, "b": 2}]


async def test_disconnect_flushes_a_pending_batch(mqtt_module, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        mqtt_module, "async_dispatcher_send", lambda _h, _s, data: sent.append(data)
    )
    client = mqtt_module.LumentreeMqttClient(_LoopHass(), None, "SN1", "SN1")

    client._queue_update({"a": 1})
    await client.disconnect()

    assert {"a": 1} in sent
    assert client._batch_timer is None
