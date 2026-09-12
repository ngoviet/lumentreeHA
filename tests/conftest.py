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

import importlib.util
import socket
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Home Assistant is not a dependency of this suite.  The modules under test
# (the MQTT payload parser and the cache store) are plain Python; only their
# module-level imports need these names to exist.
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

for _name in _HA_STUBS:
    sys.modules.setdefault(_name, MagicMock())

# const.py calls these two at import time to build its timezone helper.
sys.modules["homeassistant.util.dt"].get_time_zone = MagicMock(return_value=None)
sys.modules["homeassistant.util.dt"].get_default_time_zone = MagicMock(return_value=None)


def _package(dotted: str, path: Path) -> types.ModuleType:
    module = types.ModuleType(dotted)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
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
    stub.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
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
        socket.socket = _true_socket
        return _true_socketpair(*args, **kwargs)
    finally:
        socket.socket = guard


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
