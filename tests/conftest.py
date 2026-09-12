"""Pytest configuration for the Lumentree integration tests.

This repo is a Home Assistant custom integration with ``content_in_root: true``,
so the repository root *is* the ``lumentree`` package and every module uses
relative imports (``from ..const import ...``).  Those only resolve if the
package is importable under a parent package, and Home Assistant requires that
parent to be named ``custom_components`` -- which exists nowhere on disk.

So this module synthesises it: the Home Assistant names the integration touches
at import time are stubbed, and the real modules are then loaded by path under
``custom_components.lumentree.*``.  This runs at conftest import time, before
pytest collects any test module, so tests can import constants normally.

There is deliberately no ``tests/__init__.py``: with one present, pytest walks
up to the repository root, tries to import it as a package, and fails on the
Home Assistant import inside ``__init__.py``.

The repository root *does* have an ``__init__.py``, which pytest 9 turns into a
``Package`` collector and imports during setup.  A stub is pre-registered under
the name pytest derives from the checkout directory so that step is a no-op;
without it collection dies on ``__init__.py``'s Home Assistant imports before a
single test runs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent


# --- Windows event loop ------------------------------------------------------
# Home Assistant's aiohttp connector wires in ``aiodns`` whenever the running
# loop is a ``SelectorEventLoop``, and ``aiodns`` raises outright when it is
# not: "aiodns needs a SelectorEventLoop on Windows".  Windows defaults to
# ``ProactorEventLoop``, so any test that lets the integration build its own
# ``async_get_clientsession`` dies inside setup, before its first assertion.
# Linux (and therefore CI) is unaffected.
#
# The policy cannot simply be replaced: ``pytest_homeassistant_custom_component``
# installs ``HassEventLoopPolicy`` at plugin import and then hard-disables
# further changes with ``asyncio.set_event_loop_policy = lambda policy: None``.
# That policy subclasses ``DefaultEventLoopPolicy`` and leaves ``_loop_factory``
# at the platform default, so the loop it builds is a Proactor loop.  Swapping
# ``_loop_factory`` is what actually selects the loop; it must happen here,
# before the pytest plugin applies its lock.
if sys.platform == "win32":
    _policy = asyncio.get_event_loop_policy()
    if getattr(_policy, "_loop_factory", None) is not asyncio.SelectorEventLoop:
        _policy._loop_factory = asyncio.SelectorEventLoop  # type: ignore[attr-defined]

# Home Assistant is an optional dependency of this suite.  The modules under
# test (the MQTT payload parser and the cache store) are plain Python; only
# their module-level imports need these names to exist.  The end-to-end test
# does need the real package, so probe for it before deciding which way to go.
#
# The probe must happen here rather than lazily: these names go into
# ``sys.modules`` before any test module imports them, and a stubbed entry that
# is already in ``sys.modules`` shadows a perfectly good installed package for
# the rest of the run.
def _home_assistant_installed() -> bool:
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_REAL_HA = _home_assistant_installed()

_HA_STUBS = (
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.util",
    "homeassistant.util.dt",
)

if not _HAS_REAL_HA:
    for _name in _HA_STUBS:
        sys.modules.setdefault(_name, MagicMock())

    # const.py calls these two at import time to build its timezone helper.
    sys.modules["homeassistant.util.dt"].get_time_zone = MagicMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"].get_default_time_zone = MagicMock(return_value=None)  # type: ignore[attr-defined]


def _package(dotted: str, path: Path) -> types.ModuleType:
    module = types.ModuleType(dotted)
    module.__path__ = [str(path)]
    module.__package__ = dotted
    sys.modules[dotted] = module
    return module


def _module(dotted: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(dotted, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


# The synthesised parent: Home Assistant resolves custom integrations under
# custom_components.<domain>, so the name is not a free choice.
_package("custom_components", ROOT.parent)
_package("custom_components.lumentree", ROOT)
_package("custom_components.lumentree.core", ROOT / "core")
_package("custom_components.lumentree.services", ROOT / "services")

const = _module("custom_components.lumentree.const", ROOT / "const.py")
parser = _module(
    "custom_components.lumentree.core.realtime_parser",
    ROOT / "core" / "realtime_parser.py",
)
cache = _module("custom_components.lumentree.services.cache", ROOT / "services" / "cache.py")
# api_client imports the exception hierarchy by relative import, so its package
# sibling has to be in sys.modules before it is exec'd.
_module("custom_components.lumentree.core.exceptions", ROOT / "core" / "exceptions.py")
api_client = _module("custom_components.lumentree.core.api_client", ROOT / "core" / "api_client.py")


# pytest collects the root-level ``__init__.py`` as a ``Package`` and imports it
# during setup, under the name its own path resolution derives for the checkout
# directory.  For an ordinary clone that is the directory name (here
# "lumentreeHA"); when the directory name is not a valid Python identifier -- a
# git worktree, a CI checkout id -- pytest falls back to ``Path.stem``, and the
# relative imports inside ``__init__.py`` then die with "attempted relative
# import with no known parent package" before a single test runs.  Every name
# that resolution can yield is registered as an empty module carrying the root's
# real ``__path__``, so the import is a no-op either way.
def _root_stub(dotted: str) -> types.ModuleType:
    stub = types.ModuleType(dotted)
    stub.__path__ = [str(ROOT)]
    stub.__package__ = dotted
    stub.__file__ = str(ROOT / "__init__.py")
    sys.modules[dotted] = stub
    return stub


_root_stub(ROOT.name)
if not ROOT.name.isidentifier():
    # What pytest's fallback resolves to: the path stem of the root __init__.py.
    _root_stub("__init__")


# --- event-loop construction vs. pytest-socket's guard -----------------------
# pytest-homeassistant-custom-component's autouse fixtures
# (``enable_event_loop_debug``, ``verify_cleanup``) depend on pytest-asyncio's
# ``event_loop`` fixture, while its ``pytest_runtest_setup`` calls
# ``pytest_socket.disable_socket(allow_unix_socket=True)`` -- which replaces
# ``socket.socket`` with a guard that raises ``SocketBlockedError``.
#
# On Windows every event loop policy builds its self-pipe through
# ``socket.socketpair()``, and ``socket.py``'s ``_fallback_socketpair`` creates
# the pair via the module-level ``socket.socket`` name.  The ban therefore
# blocks *event loop construction* rather than test network access, and every
# test errors during fixture setup.  ``allow_unix_socket=True`` cannot help:
# Windows has no ``AF_UNIX``, so ``pytest_socket._is_unix_socket`` is always
# False.  (CPython exposes no ``_socket.socketpair`` on Windows, so the fallback
# is the only path.)
#
# Re-expose the real constructor for this one stdlib-internal call site.  The
# guard stays in force everywhere else -- a test calling ``socket.socket()``
# still raises and ``socket.socket.connect`` is still host-restricted -- so no
# test gains network access it did not have.
_true_socket = socket.socket
_true_socketpair = socket.socketpair


def _socketpair_bypassing_the_guard(*args, **kwargs):
    """``socket.socketpair()``, with pytest-socket's ``socket.socket`` lifted."""
    guard = socket.socket
    try:
        socket.socket = _true_socket  # type: ignore[misc]
        return _true_socketpair(*args, **kwargs)
    finally:
        socket.socket = guard  # type: ignore[misc]


if sys.platform == "win32":
    socket.socketpair = _socketpair_bypassing_the_guard


@pytest.fixture(scope="session")
def lumentree_const():
    return const


@pytest.fixture(scope="session")
def lumentree_parser():
    return parser


@pytest.fixture(scope="session")
def lumentree_cache():
    return cache


@pytest.fixture(scope="session")
def lumentree_api_client():
    return api_client
