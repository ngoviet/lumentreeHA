"""Thread-affinity regression tests for the MQTT client.

Home Assistant records a violation (and, on some versions, raises) whenever an
event-loop-only API is reached from another thread.  The deployed integration
logged 16 of these:

    File "concurrent/futures/thread.py", line 86, in run
      File "core/mqtt_client.py", line 224, in <lambda>
        lambda _now: self._set_offline(gen)
      File "core/mqtt_client.py", line 211, in _set_offline
        async_dispatcher_send(...)
    RuntimeError: Detected that custom integration 'lumentree' calls
    async_dispatcher_send from a thread other than the event loop

The cause was not the paho callbacks -- those already marshalled correctly --
but the bare ``lambda`` handed to ``async_call_later``: Home Assistant runs a
lambda without ``@callback`` in an executor thread, so ``_set_offline`` ran off
the loop and called the dispatcher from there.

These tests pin the contract that ``_set_offline`` is safe from any thread and
that the dispatcher always runs on the loop.
"""

from __future__ import annotations

import asyncio
import threading

import pytest


@pytest.fixture(scope="session")
def mqtt_client_module():
    """The real core.mqtt_client, loaded by conftest's package shim."""
    from custom_components.lumentree.core import mqtt_client

    return mqtt_client


class _FakeHass:
    """Minimal stand-in: only the attributes the client actually touches."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


@pytest.fixture
def client_and_loop(mqtt_client_module):
    """A client bound to a real event loop running on a dedicated thread.

    The loop thread is deliberately distinct from the test's own thread so that
    "which thread did this run on" is unambiguous.
    """
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True, name="ha-event-loop")
    thread.start()
    assert ready.wait(5), "event loop thread did not start"

    client = mqtt_client_module.LumentreeMqttClient(
        _FakeHass(loop), entry=None, device_sn="H240909079", device_id="test"
    )
    try:
        yield client, loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def _run_on_loop(loop: asyncio.AbstractEventLoop, func, timeout: float = 5.0):
    """Run ``func`` on the loop thread and return its result."""
    done = threading.Event()
    box: list = []

    def _call() -> None:
        try:
            box.append(("ok", func()))
        except BaseException as exc:  # noqa: BLE001 - surfaced to the caller
            box.append(("err", exc))
        finally:
            done.set()

    loop.call_soon_threadsafe(_call)
    assert done.wait(timeout), "call did not complete on the loop"
    kind, value = box[0]
    if kind == "err":
        raise value
    return value


def _drain(loop: asyncio.AbstractEventLoop) -> None:
    """Let every callback already scheduled on the loop run to completion.

    ``asyncio.sleep(0)`` yields once, which is enough for a ``call_soon`` that
    was queued before this coroutine was submitted.
    """
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=5)


def _hold_loop(loop: asyncio.AbstractEventLoop, timeout: float = 5.0) -> threading.Event:
    """Block the loop thread and return the event that releases it.

    Asserting "the dispatcher was not reached" is only meaningful while the
    loop is unable to run, otherwise a free-running loop may execute the
    marshalled callback before the assertion -- which made this test flaky.
    Returns once the loop is provably inside the blocking callback.
    """
    started = threading.Event()
    release = threading.Event()

    def _block() -> None:
        started.set()
        release.wait(timeout)

    loop.call_soon_threadsafe(_block)
    assert started.wait(timeout), "loop did not enter the hold"
    return release


@pytest.fixture
def dispatched_from(mqtt_client_module, monkeypatch):
    """Patch the dispatcher and record the thread name of each dispatch."""
    calls: list[str] = []
    monkeypatch.setattr(
        mqtt_client_module,
        "async_dispatcher_send",
        lambda *a, **k: calls.append(threading.current_thread().name),
    )
    return calls


def test_set_offline_from_foreign_thread_defers_dispatch(
    client_and_loop, dispatched_from
) -> None:
    """The dispatcher must not be reached on the calling thread.

    Before the fix this failed: ``_set_offline`` ran inline on the worker
    thread and called ``async_dispatcher_send`` there.
    """
    client, loop = client_and_loop

    # Online, so the offline transition actually dispatches.
    client._online = True

    # Park the loop so the marshalled callback cannot run before the assertion.
    release = _hold_loop(loop)
    try:
        worker = threading.Thread(target=client._set_offline, name="paho-sim")
        worker.start()
        worker.join(5)
        assert not worker.is_alive(), "thread-calling _set_offline did not return"

        # The dispatch is scheduled, not performed on the worker thread.
        assert dispatched_from == [], (
            "async_dispatcher_send ran on the calling thread; it must be marshalled"
        )
    finally:
        release.set()

    # ... and it does happen once the loop drains.
    _drain(loop)
    assert dispatched_from == ["ha-event-loop"], f"dispatched from {dispatched_from!r}"


def test_set_offline_from_loop_thread_dispatches_inline(
    client_and_loop, dispatched_from
) -> None:
    """On the loop there is nothing to marshal -- the dispatch is immediate."""
    client, loop = client_and_loop

    client._online = True
    _run_on_loop(loop, client._set_offline)

    assert dispatched_from == ["ha-event-loop"], f"dispatched from {dispatched_from!r}"


def test_set_offline_is_idempotent_when_already_offline(
    client_and_loop, dispatched_from
) -> None:
    """A second offline transition must not re-dispatch."""
    client, loop = client_and_loop

    client._online = True
    _run_on_loop(loop, client._set_offline)
    assert client._online is False
    assert len(dispatched_from) == 1

    _run_on_loop(loop, client._set_offline)
    assert len(dispatched_from) == 1, "already-offline must not dispatch again"


def test_stale_timer_generation_is_ignored(client_and_loop, dispatched_from) -> None:
    """A timer callback from a superseded generation must be a no-op.

    This is the guard that makes it safe for the offline timer to be restarted
    on every message.
    """
    client, loop = client_and_loop

    client._online = True
    client._offline_timer_gen = 7

    # gen=3 was superseded by gen=7.
    _run_on_loop(loop, lambda: client._set_offline(3))

    assert dispatched_from == [], "a stale timer generation must not dispatch"
    assert client._online is True, "a stale generation must not flip the state"


def test_call_soon_executes_on_loop_from_any_thread(client_and_loop) -> None:
    """``_call_soon`` is the shared marshalling primitive; pin its contract."""
    client, loop = client_and_loop

    seen: list[str] = []
    worker = threading.Thread(
        target=lambda: client._call_soon(
            lambda: seen.append(threading.current_thread().name)
        ),
        name="paho-sim",
    )
    worker.start()
    worker.join(5)

    _drain(loop)
    assert seen == ["ha-event-loop"], f"ran on {seen!r}"
