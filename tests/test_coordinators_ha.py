"""Statistics coordinators and service targeting, against real Home Assistant.

Pins three counting bugs and one routing bug:

* lifetime totals added the current year twice once more than one year was
  cached (its "latest year" was really the oldest);
* the monthly total added today's live reading on top of a cached partial row
  for today, and right after midnight added yesterday's final totals as
  "today";
* the yearly totals came from getYearData, which answers with last year;
* services registered per config entry acted on whichever inverter loaded last.

Skipped unless Home Assistant is installed, like the end-to-end suite.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

# conftest stubs the homeassistant modules when HA is absent, so importing them
# proves nothing; the test plugin is the real availability probe.
try:
    import pytest_homeassistant_custom_component  # noqa: F401
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.util import dt as dt_util

    HA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without Home Assistant
    HA_AVAILABLE = False

pytestmark = pytest.mark.skipif(not HA_AVAILABLE, reason="homeassistant is not installed")

DOMAIN = "lumentree"
ENTRY_ID = "entry-1"


@pytest.fixture
def cache_io(tmp_path):
    from custom_components.lumentree.services import cache

    original = cache.CACHE_BASE_DIR
    cache.set_base_dir(str(tmp_path))
    yield cache
    cache.set_base_dir(original)


def _write_days(cache_io, year: int, days: dict[str, dict[str, float]]) -> None:
    cache = cache_io._empty_cache()
    for date_str, values in days.items():
        cache_io.update_daily(cache, date_str, values)
    cache_io.save_year("DEV1", year, cache_io.recompute_aggregates(cache))


def _aggregator():
    return SimpleNamespace(_device_id="DEV1")


def _now(hass: HomeAssistant) -> dt.datetime:
    now: dt.datetime = dt_util.now(dt_util.get_time_zone(hass.config.time_zone))
    return now


async def test_lifetime_total_counts_the_current_year_once(hass: HomeAssistant, cache_io):
    from custom_components.lumentree.const import KEY_TOTAL_PV_KWH, KEY_YEARLY_PV_KWH
    from custom_components.lumentree.coordinators.total_coordinator import TotalStatsCoordinator

    year = _now(hass).year
    _write_days(cache_io, year - 1, {f"{year - 1}-03-01": {"pv": 10.0}})
    _write_days(cache_io, year, {f"{year}-01-01": {"pv": 4.0}})
    hass.data[DOMAIN] = {
        ENTRY_ID: {
            "yearly_coordinator": SimpleNamespace(data={"year": year, KEY_YEARLY_PV_KWH: 7.0})
        }
    }

    coord = TotalStatsCoordinator(hass, _aggregator(), "SN1", ENTRY_ID)
    data = await coord._async_update_data()

    # Last year from the cache, this year from the yearly coordinator -- not
    # both, and not this year's cache on top.
    assert data[KEY_TOTAL_PV_KWH] == pytest.approx(17.0)
    assert (data["earliest_year"], data["latest_year"]) == (year - 1, year)

    # Without a yearly coordinator the cached current year stands in.
    hass.data[DOMAIN] = {ENTRY_ID: {}}
    data = await coord._async_update_data()
    assert data[KEY_TOTAL_PV_KWH] == pytest.approx(14.0)


async def test_monthly_total_does_not_double_count_today(hass: HomeAssistant, cache_io):
    from custom_components.lumentree.const import KEY_MONTHLY_PV_KWH
    from custom_components.lumentree.coordinators.monthly_coordinator import (
        MonthlyStatsCoordinator,
    )

    today = _now(hass).date()
    days = {today.isoformat(): {"pv": 2.0}}  # a partial row an old version cached
    if today.day > 1:
        days[(today - dt.timedelta(days=1)).isoformat()] = {"pv": 5.0}
    _write_days(cache_io, today.year, days)
    past = 5.0 if today.day > 1 else 0.0

    daily = SimpleNamespace(data={"pv_today": 3.0, "source_date": today.isoformat()})
    hass.data[DOMAIN] = {ENTRY_ID: {"daily_coordinator": daily}}
    coord = MonthlyStatsCoordinator(hass, _aggregator(), "SN1", ENTRY_ID)

    data = await coord._async_update_data()
    assert data[KEY_MONTHLY_PV_KWH] == pytest.approx(past + 3.0)
    assert data["daily_pv"][today.day - 1] == 3.0
    assert sum(data["daily_pv"]) == pytest.approx(data[KEY_MONTHLY_PV_KWH])

    # Just after midnight the daily coordinator still holds yesterday.
    daily.data = {"pv_today": 9.0, "source_date": "1999-01-01"}
    data = await coord._async_update_data()
    assert data[KEY_MONTHLY_PV_KWH] == pytest.approx(past)


async def test_yearly_total_ignores_stale_monthly_arrays(hass: HomeAssistant, cache_io):
    from custom_components.lumentree.const import KEY_MONTHLY_PV_KWH, KEY_YEARLY_PV_KWH
    from custom_components.lumentree.coordinators.yearly_coordinator import (
        YearlyStatsCoordinator,
    )

    now = _now(hass)
    year = now.year
    finished_month = 1 if now.month > 1 else None
    days = {f"{year}-01-0{d}": {"pv": 1.0} for d in range(1, 4)} if finished_month else {}
    _write_days(cache_io, year, days)
    # What earlier versions persisted: getYearData's (last year's) months.
    cache = cache_io.load_year("DEV1", year, auto_recompute=False)
    cache["monthly"]["pv"] = [500.0] * 12
    cache_io.save_year("DEV1", year, cache)

    monthly = SimpleNamespace(data={"year": year, "month": now.month, KEY_MONTHLY_PV_KWH: 2.5})
    hass.data[DOMAIN] = {ENTRY_ID: {"monthly_coordinator": monthly}}
    coord = YearlyStatsCoordinator(hass, _aggregator(), "SN1", ENTRY_ID)

    data = await coord._async_update_data()

    expected = (3.0 if finished_month else 0.0) + 2.5
    assert data[KEY_YEARLY_PV_KWH] == pytest.approx(expected)
    assert data["monthly_pv"][now.month - 1] == 2.5
    repaired = cache_io.load_year("DEV1", year, auto_recompute=False)
    assert repaired["monthly"]["pv"] != [500.0] * 12, "stale monthly arrays were kept"


@pytest.fixture
def integration_module():
    """The shipping __init__.py, executed into the conftest package stub."""
    import pathlib

    import custom_components.lumentree as package

    init_py = pathlib.Path(__file__).resolve().parent.parent / "__init__.py"
    exec(compile(init_py.read_text(encoding="utf-8"), str(init_py), "exec"), package.__dict__)
    return package


def test_service_targets_follow_device_sn(hass: HomeAssistant, integration_module):
    hass.data[DOMAIN] = {
        "a": {"aggregator": object(), "device_sn": "SN-A", "device_id": "ID-A"},
        "b": {"aggregator": object(), "device_sn": "SN-B", "device_id": "ID-B"},
        "half-set-up": {"device_sn": "SN-C"},
    }
    targets = integration_module._target_entries

    assert [d["device_sn"] for d in targets(hass, SimpleNamespace(data={}))] == ["SN-A", "SN-B"]
    assert [d["device_sn"] for d in targets(hass, SimpleNamespace(data={"device_sn": "SN-B"}))] == [
        "SN-B"
    ]
    assert [d["device_sn"] for d in targets(hass, SimpleNamespace(data={"device_sn": "ID-A"}))] == [
        "SN-A"
    ]
    with pytest.raises(HomeAssistantError):
        targets(hass, SimpleNamespace(data={"device_sn": "SN-C"}))
    hass.data[DOMAIN] = {}
    with pytest.raises(HomeAssistantError):
        targets(hass, SimpleNamespace(data={}))


async def test_services_are_registered_once(hass: HomeAssistant, integration_module):
    assert await integration_module.async_setup(hass, {})
    assert await integration_module.async_setup(hass, {})
    services = hass.services.async_services().get(DOMAIN, {})
    assert {"smart_backfill", "purge_cache", "mark_empty_dates"} <= set(services)
