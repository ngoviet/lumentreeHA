# Development Notes

Traps this repository sets, and what was measured about each. Every entry here
cost real debugging time to find; none of it is guesswork. Read this before
changing the test harness, the layout, or anything that touches the vendor dump.

## Running the tests

There are two environments, and they collect different numbers:

```bash
# CI's environment: pytest + aiohttp + paho + crcmod only.
# Home Assistant is absent, so the end-to-end test skips.
python -m pytest tests/ -q     # 80 passed, 6 skipped

# The real end-to-end harness: a virtualenv with Home Assistant and
# pytest-homeassistant-custom-component installed.  The interpreter path is
# local to the author's machine -- point this at your own environment.
"<venv>/Scripts/python.exe" -m pytest tests/ -q   # 86 passed
```

The end-to-end test (`tests/test_e2e_mqtt_to_entity.py`) **skips**, it does not
fail, when Home Assistant is missing. That is deliberate: it means `pytest
tests/` on a bare interpreter still passes, and CI stays green without carrying
a full Home Assistant install.

## `content_in_root: true` breaks Home Assistant's loader

`hacs.json` sets `content_in_root: true`, so the repository root *is* the
`lumentree` package and there is no `custom_components/lumentree/` directory.
HA's `Integration.resolve_from_root` looks for
`custom_components/lumentree/manifest.json`, finds nothing, and the integration
is invisible to it.

The end-to-end test works around this by building
`homeassistant.loader.Integration` directly from the real `manifest.json` and
registering it in `hass.data[loader.DATA_INTEGRATIONS]["lumentree"]`.

The same layout is why hassfest reports `[MANIFEST] Domain does not match dir
name` and always will: hassfest compares `manifest["domain"]` against the
directory name it discovered, and for a root layout that name is the checkout
directory. There is no `content_in_root` exemption in hassfest
(home-assistant/core#152942 was closed `not_planned`). CI works around it by
checking out into `custom_components/lumentree` — see `.github/workflows/ci.yml`.

## Things that look like bugs but are not

**Entities with no state.** Seven entities ship `entity_registry_enabled_default
= False`. Home Assistant registers those but deliberately creates **no state**
until a user enables them, so `hass.states.get(entity_id)` returns `None`.
A test that asserts every registered entity has state will fail on a healthy
integration. Iterate `entity_registry`, skip entries whose `disabled_by` is not
`None`, and keep their keys in a separate set if a drift check needs to count
them.

**A corrupted vendor dump.** `mqtt_discovery.json` holds ~4,350 captured MQTT
payloads and looks like a ready-made frame fixture. It is not usable: its
non-ASCII bytes have been flattened to U+FFFD, so the frames cannot be
re-encoded and **zero** of them pass CRC. Build frames with the `_crc16` /
`build_frame` helpers in `tests/test_realtime_parser.py` instead, and say so in
the test — a comment claiming a frame was "captured" when it was constructed is
worse than no comment.

## Home Assistant test harness gotchas

**`asyncio.create_task` is invisible to `async_block_till_done()`.** The MQTT
client's `_queue_update` coalesces frames into a 100 ms `asyncio.create_task`
that HA never tracked, so `await hass.async_block_till_done()` returns before it
runs. A test that delivers a frame and immediately asserts on entity state will
see `unknown`. Sleep past the coalescing window first, then block:

```python
await asyncio.sleep(0.15)
await hass.async_block_till_done()
```

**`verify_cleanup` fails on lingering timers.** HA's autouse fixture fails the
test if any `async_track_time_interval` or `async_call_later` job is still
pending at teardown. Setup arms a 5 s poll timer and a nightly timer, so the
config-entry fixture must unload the entry — and the fixture must be **async**,
because `hass.config_entries.async_unload` returns a coroutine. A sync fixture
calling it without `await` silently does nothing and the test still fails.

The same hazard runs the other way: if a test stubs `disconnect` to a no-op, it
also blocks the `_cancel_offline_timer()` call inside it and leaks a 12.5 s
`async_call_later`. Stub only `connect`, and let the real `disconnect` run — with
no `_mqtt_client` behind it, its body is just the cancel calls.

**`aioclient_mock`'s responses have no `.ok`.** `aiohttp.ClientResponse.ok` is
what `api_client._request` reads, and HA's mocker produces a response object
with `.status` but not `.ok`. Wrap `aioclient_mock.match_request` to derive it,
keeping the shim at the mock boundary instead of changing shipping code to
accommodate a test double. Note also that `respx` does **not** intercept HA's
session — only `aioclient_mock` does.

**Windows needs a `SelectorEventLoop`, and the policy setter is disabled.**
`aiodns` raises outright on a `ProactorEventLoop`, which is the Windows
default, so any test that lets the integration build its own session dies
inside setup. The policy cannot simply be replaced:
`pytest_homeassistant_custom_component` installs `HassEventLoopPolicy` at plugin
import and then hard-disables `asyncio.set_event_loop_policy` with a lambda.
Patch `_loop_factory` on the existing policy instead — see the top of
`tests/conftest.py`. Linux and CI are unaffected.

**pytest-socket blocks event-loop construction on Windows.** HA's autouse
fixtures call `pytest_socket.disable_socket(allow_unix_socket=True)`, which
replaces `socket.socket` with a guard. Every Windows event loop builds its
self-pipe through `socket.socketpair()`, and the fallback implementation uses
the module-level `socket.socket` name — so the network ban blocks *loop
construction* and every test errors during fixture setup. `allow_unix_socket`
cannot help; Windows has no `AF_UNIX`. `tests/conftest.py` re-exposes the real
constructor for that one stdlib-internal call site.

## Landmines in the build

**`_STAGGER_DELAY_SECONDS`.** `__init__.py` waits ten seconds between warming
the daily coordinator and the stats coordinators, so a backfill can land. It is
a module-level constant so the test can shrink it to 0.01; leaving it inline as
a literal `asyncio.sleep(10)` made the end-to-end suite take 61 seconds instead
of 1.3.

**`asyncio.timeout` requires Python 3.11+**, which is why the integration
declares that floor.

**The effective Home Assistant floor is 2024.4, not the `2023.1.0` in
`hacs.json`.** `config_flow.py` does a runtime `from
homeassistant.config_entries import ConfigFlowResult`, and that symbol only
exists from 2024.4. On 2023.1–2024.3 the integration installs and then fails at
setup.

## Git and history

`main` on GitHub has been rewritten more than once during this project's
cleaning passes. Before treating any local commit as "unmerged", check whether
its *content* already landed via a different commit — a stale local `main` can
sit 14 behind and 3 "ahead" while every one of those three commits is already
present upstream under another hash.

## Secret handling

The vendor MQTT credentials (`MQTT_USERNAME` / `MQTT_PASSWORD` in `const.py`)
are masked rather than removed. They ship in plaintext inside the vendor's own
Android app, so they are public by construction and no client-side scheme can
keep them secret — the masking only stops them turning up in a text search of
this repository. See the `_unmask` docstring, which says exactly that.

Two older credential values from the discovery work (a request-signing salt and
a suspected AES key) are absent from the current tree, but they do remain in
older commits that are already public on GitHub. They were left alone
deliberately: rewriting public history to remove a value that is already
mirrored and cached causes more damage than it prevents. Do not reintroduce
them into new files.

Rules for anything placed under `docs/`:

- `token`, `uid`, `nickname`, `phone` are redacted to `<redacted>`.
- Probe records must not carry a live token. The ones committed here were
  scanned for JWTs, `uid`/`nickname`/`phone` fields, and IP addresses; all
  clean.
- `tools/` is gitignored and contains `emqx_clients.json` (128 MB of vendor
  MQTT client records plus EMQX admin credentials). It must never be committed.
