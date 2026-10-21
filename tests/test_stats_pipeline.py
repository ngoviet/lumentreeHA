"""Regression tests for the statistics pipeline: smart backfill and the year cache.

Each test pins one defect that shipped:

* smart backfill wrote the reading of the day in progress, and zero rows for
  the rest of the month, into the cache -- after which every backfill and the
  midnight finaliser skipped those dates, freezing partial totals for good;
* ``get_month_data`` dropped ``batF``, so every backfilled day had zero
  discharge;
* ``save_year`` never wrote the ``.bak`` that ``load_year`` restores from.

None of these needs Home Assistant, so the file runs in CI.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import pytest
from custom_components.lumentree.core.exceptions import ApiException
from custom_components.lumentree.services import smart_backfill as sb

TODAY = dt.date(2026, 9, 12)


def _month(**series: list[float]) -> dict[str, list[float]]:
    """A get_month_data() result (kWh), 31 slots, unnamed metrics all zero."""
    out = {key: [0.0] * 31 for key in ("pv", "grid", "homeload", "essentialLoad", "bat", "batF")}
    for key, values in series.items():
        out[key] = list(values) + [0.0] * (31 - len(values))
    return out


# --- merge_month ------------------------------------------------------------


def test_merge_month_never_writes_today_or_later(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    data = _month(pv=[1.0] * 31, homeload=[2.0] * 31)

    added, updated, has_data = sb.merge_month(cache, 2026, 9, data, TODAY)

    assert has_data
    assert (added, updated) == (11, 0)
    assert sorted(cache["daily"]) == [f"2026-09-{d:02d}" for d in range(1, 12)]
    assert "2026-09-12" not in cache["daily"], "the day in progress was cached"
    assert "2026-09-12" not in cache["meta"]["empty_dates"]


def test_merge_month_keeps_discharge(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    data = _month(pv=[5.0, 5.0], bat=[1.5, 0.0], batF=[2.5, 3.0])

    sb.merge_month(cache, 2026, 9, data, TODAY)

    assert cache["daily"]["2026-09-01"]["charge"] == 1.5
    assert cache["daily"]["2026-09-01"]["discharge"] == 2.5
    assert cache["daily"]["2026-09-02"]["discharge"] == 3.0


def test_merge_month_raises_a_partial_day_metric_by_metric(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    # A reading taken mid-day, with a load figure higher than the API's.
    lumentree_cache.update_daily(
        cache, "2026-09-05", {"pv": 1.0, "load": 9.0, "grid": 0.5, "discharge": 0.0}
    )
    data = _month(
        pv=[0, 0, 0, 0, 6.0],
        homeload=[0, 0, 0, 0, 8.0],
        grid=[0, 0, 0, 0, 0.5],
        batF=[0, 0, 0, 0, 1.2],
    )

    _added, updated, _has = sb.merge_month(cache, 2026, 9, data, TODAY)

    day = cache["daily"]["2026-09-05"]
    assert updated == 1
    assert day["pv"] == 6.0, "the partial PV total was not replaced"
    assert day["discharge"] == 1.2, "the dropped discharge was not repaired"
    assert day["load"] == 9.0, "a higher cached value must not be lowered"
    assert day["total_load"] == 9.0


def test_merge_month_leaves_matching_days_alone(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    lumentree_cache.update_daily(cache, "2026-09-01", {"pv": 5.0})

    _added, updated, _has = sb.merge_month(cache, 2026, 9, _month(pv=[5.0]), TODAY)

    assert updated == 0


def test_merge_month_marks_days_without_data_empty(lumentree_cache):
    cache = lumentree_cache._empty_cache()

    added, _updated, has_data = sb.merge_month(cache, 2026, 8, _month(), TODAY)

    assert not has_data
    assert added == 31
    assert cache["daily"] == {}
    assert len(cache["meta"]["empty_dates"]) == 31


def test_merge_month_leaves_days_a_truncated_answer_never_reported(lumentree_cache):
    """A series that stops at day 10 says nothing about days 11..31.

    Those days used to be read as zero and marked empty, after which the month
    counted as complete and was never asked for again.
    """
    cache = lumentree_cache._empty_cache()
    truncated = _month(pv=[4.0] * 31, grid=[1.0] * 31)
    truncated["homeload"] = [3.0] * 10

    added, _updated, _has = sb.merge_month(cache, 2026, 8, truncated, TODAY)

    assert added == 10
    assert sorted(cache["daily"]) == [f"2026-08-{d:02d}" for d in range(1, 11)]
    assert cache["meta"]["empty_dates"] == []
    assert not sb._month_is_complete(cache, 2026, 8, TODAY), "the month must be asked again"

    full = _month(pv=[4.0] * 31, grid=[1.0] * 31, homeload=[3.0] * 31)
    added, _updated, _has = sb.merge_month(cache, 2026, 8, full, TODAY)
    assert added == 21
    assert sb._month_is_complete(cache, 2026, 8, TODAY)


def test_merge_month_without_any_required_series_is_a_month_without_data(lumentree_cache):
    """All required series empty is "no data", not a truncation."""
    cache = lumentree_cache._empty_cache()
    empty = {key: [] for key in ("pv", "grid", "homeload", "essentialLoad", "bat", "batF")}

    added, _updated, has_data = sb.merge_month(cache, 2026, 8, empty, TODAY)

    assert not has_data
    assert added == 31
    assert len(cache["meta"]["empty_dates"]) == 31


def test_drop_unfinished_days(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    for date in ("2026-09-11", "2026-09-12", "2026-09-30"):
        lumentree_cache.update_daily(cache, date, {"pv": 1.0})
    lumentree_cache.mark_empty(cache, "2026-09-13")
    lumentree_cache.mark_empty(cache, "2026-09-01")

    assert sb.drop_unfinished_days(cache, TODAY)
    assert list(cache["daily"]) == ["2026-09-11"]
    assert cache["meta"]["empty_dates"] == ["2026-09-01"]
    assert not sb.drop_unfinished_days(cache, TODAY), "second pass should be a no-op"


def test_month_is_complete(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    for day in range(1, 31):
        lumentree_cache.update_daily(cache, f"2026-08-{day:02d}", {"pv": 1.0})
    assert not sb._month_is_complete(cache, 2026, 8, TODAY), "Aug 31 is missing"
    lumentree_cache.mark_empty(cache, "2026-08-31")
    assert sb._month_is_complete(cache, 2026, 8, TODAY)
    assert not sb._month_is_complete(cache, 2026, 9, TODAY), "the current month never is"


# --- smart_backfill ----------------------------------------------------------


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeApi:
    """get_month_data() from a table, recording every request."""

    def __init__(self, months: dict[tuple[int, int], dict[str, list[float]]]) -> None:
        self.months = months
        self.calls: list[tuple[int, int]] = []

    async def get_month_data(self, device_id: str, year: int, month: int) -> dict:
        self.calls.append((year, month))
        return self.months.get((year, month), _month())


class _FakeAggregator:
    def __init__(self, api: _FakeApi) -> None:
        self._device_id = "DEV1"
        self._api = api


@pytest.fixture
def backfill_env(lumentree_cache, tmp_path, monkeypatch):
    original_base = lumentree_cache.CACHE_BASE_DIR
    lumentree_cache.set_base_dir(str(tmp_path))
    monkeypatch.setattr(sb, "today_in_ha", lambda hass: TODAY)
    monkeypatch.setattr(sb, "_REQUEST_DELAY_SECONDS", 0)
    yield lumentree_cache
    lumentree_cache.set_base_dir(original_base)


def _run(api: _FakeApi, **kwargs: Any) -> dict:
    kwargs.setdefault("optimize_cache", False)
    return asyncio.run(sb.smart_backfill(_FakeHass(), _FakeAggregator(api), **kwargs))


def test_smart_backfill_skips_complete_months_on_the_next_run(backfill_env):
    api = _FakeApi(
        {(2026, m): _month(pv=[float(m)] * 31) for m in range(1, 10)}
        | {(2025, m): _month(pv=[0.25 + m / 100] * 31) for m in range(1, 13)}
    )

    first = _run(api, max_years=3)

    assert first["years_with_data"] == [2026, 2025]
    # 2026 Sep..Jan, 2025 Dec..Jan, then 2024 (empty: the walk stops there).
    assert len(api.calls) == 9 + 12 + 12
    cache = backfill_env.load_year("DEV1", 2026, auto_recompute=False)
    assert "2026-09-12" not in cache["daily"]
    assert cache["yearly_total"]["pv"] == pytest.approx(
        sum(m * backfill_env_days(2026, m) for m in range(1, 9)) + 9 * 11
    )

    api.calls.clear()
    _run(api, max_years=3)
    # Every finished month is now cached or known empty; only the month in
    # progress is asked for again.
    assert api.calls == [(2026, 9)]


def backfill_env_days(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def test_smart_backfill_stops_when_the_api_ignores_the_month(backfill_env):
    same = _month(pv=[3.0] * 31)
    api = _FakeApi({(2026, 9): same, (2026, 8): same, (2026, 7): _month(pv=[1.0] * 31)})

    _run(api, max_years=1)

    assert api.calls == [(2026, 9), (2026, 8)]
    cache = backfill_env.load_year("DEV1", 2026, auto_recompute=False)
    assert not any(d.startswith("2026-08-") for d in cache["daily"]), (
        "September's numbers were written into August"
    )


def test_smart_backfill_counts_request_errors_and_keeps_walking(backfill_env):
    class _Flaky(_FakeApi):
        async def get_month_data(self, device_id, year, month):
            if (year, month) == (2026, 8):
                self.calls.append((year, month))
                raise ApiException("boom")
            return await super().get_month_data(device_id, year, month)

    api = _Flaky({(2026, m): _month(pv=[float(m)] * 31) for m in range(1, 10)})

    stats = _run(api, max_years=1)

    assert stats["errors"] == 1
    assert (2026, 7) in api.calls


def test_smart_backfill_removes_a_cached_partial_today(backfill_env):
    cache = backfill_env._empty_cache()
    backfill_env.update_daily(cache, "2026-09-12", {"pv": 0.4})
    backfill_env.update_daily(cache, "2026-09-20", {})
    backfill_env.save_year("DEV1", 2026, cache)

    _run(_FakeApi({}), max_years=1)

    cache = backfill_env.load_year("DEV1", 2026, auto_recompute=False)
    assert "2026-09-12" not in cache["daily"]
    assert "2026-09-20" not in cache["daily"]


# --- year cache --------------------------------------------------------------


@pytest.fixture
def cache_dir(lumentree_cache, tmp_path):
    original_base = lumentree_cache.CACHE_BASE_DIR
    lumentree_cache.set_base_dir(str(tmp_path))
    yield lumentree_cache
    lumentree_cache.set_base_dir(original_base)


def test_save_year_keeps_the_previous_file_as_backup(cache_dir):
    first = cache_dir._empty_cache()
    cache_dir.update_daily(first, "2026-01-01", {"pv": 1.0})
    cache_dir.save_year("DEV1", 2026, first)
    second = cache_dir.load_year("DEV1", 2026, auto_recompute=False)
    cache_dir.update_daily(second, "2026-01-02", {"pv": 2.0})
    cache_dir.save_year("DEV1", 2026, second)

    path = cache_dir.cache_path("DEV1", 2026)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{truncated")

    restored = cache_dir.load_year("DEV1", 2026, auto_recompute=False)
    assert list(restored["daily"]) == ["2026-01-01"], "did not fall back to the .bak"


def test_load_year_restores_when_only_the_backup_exists(cache_dir):
    import os

    cache = cache_dir._empty_cache()
    cache_dir.update_daily(cache, "2026-01-01", {"pv": 1.0})
    cache_dir.save_year("DEV1", 2026, cache)
    path = cache_dir.cache_path("DEV1", 2026)
    os.replace(path, path + ".bak")

    assert "2026-01-01" in cache_dir.load_year("DEV1", 2026, auto_recompute=False)["daily"]


def test_purge_year_removes_the_backup_too(cache_dir):
    cache = cache_dir._empty_cache()
    cache_dir.update_daily(cache, "2026-01-01", {"pv": 1.0})
    cache_dir.save_year("DEV1", 2026, cache)
    cache_dir.save_year("DEV1", 2026, cache)

    assert cache_dir.purge_year("DEV1", 2026)
    assert cache_dir.load_year("DEV1", 2026)["daily"] == {}, "purge was undone by the backup"


def test_monthly_totals_can_exclude_the_day_in_progress(lumentree_cache):
    cache = lumentree_cache._empty_cache()
    lumentree_cache.update_daily(cache, "2026-09-11", {"pv": 4.0})
    lumentree_cache.update_daily(cache, "2026-09-12", {"pv": 1.5})

    assert lumentree_cache.monthly_totals(cache)["pv"][8] == 5.5
    assert lumentree_cache.monthly_totals(cache, before="2026-09-12")["pv"][8] == 4.0
    assert cache["monthly"]["pv"][8] == 5.5, "monthly_totals must not modify the cache"


# --- get_month_data ----------------------------------------------------------


class _Resp:
    def __init__(self, payload: dict) -> None:
        self.status = 200
        self.ok = True
        self._payload = payload

    async def text(self) -> str:
        return str(self._payload)

    async def json(self, content_type: str | None = None) -> dict:
        return self._payload


class _Ctx:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    async def __aenter__(self) -> _Resp:
        return self._resp

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _ScriptedSession:
    """Answers each request from a per-endpoint queue, recording the traffic."""

    def __init__(self, script: dict[str, list[dict]]) -> None:
        self.script = script
        self.requests: list[tuple[str, dict]] = []

    def request(self, method, url, headers=None, **kwargs):
        self.requests.append((url, dict(headers or {})))
        for suffix, queue in self.script.items():
            if url.endswith(suffix):
                payload = queue.pop(0) if len(queue) > 1 else queue[0]
                return _Ctx(_Resp(payload))
        raise AssertionError(f"unscripted request {url}")


def test_get_month_data_keeps_batf_and_day_positions(lumentree_api_client):
    payload = {
        "returnValue": 1,
        "data": {
            "pv": {"tableValueInfo": [10, "bad", 30]},
            "bat": {"tableValueInfo": [5, 0, 0]},
            "batF": {"tableValueInfo": [0, 12, 0]},
            "titleParams": [],
        },
    }
    client = lumentree_api_client.LumentreeHttpApiClient(
        _ScriptedSession({"getMonthData": [payload]})
    )
    client.set_token("t")

    result = asyncio.run(client.get_month_data("DEV1", 2026, 9))

    assert result["batF"] == [0.0, 1.2, 0.0]
    assert result["pv"] == [1.0, 0.0, 3.0], "an unreadable day shifted the later days"
    assert result["homeload"] == []


def test_get_month_data_raises_instead_of_reporting_an_empty_month(lumentree_api_client):
    client = lumentree_api_client.LumentreeHttpApiClient(
        _ScriptedSession({"getMonthData": [{"returnValue": 2, "msg": "nope"}]})
    )
    client.set_token("t")

    with pytest.raises(ApiException):
        asyncio.run(client.get_month_data("DEV1", 2026, 9))


# --- token renewal -----------------------------------------------------------


def _device_manage_ok() -> dict:
    return {"returnValue": 1, "data": {"devices": [{"deviceId": "DEV1"}]}}


def test_rejected_token_is_renewed_once_and_the_request_retried(lumentree_api_client):
    session = _ScriptedSession(
        {
            "deviceManage": [{"returnValue": 203, "msg": "token"}, _device_manage_ok()],
            "getServerTime": [{"returnValue": 1, "data": {"serverTime": 1700000000}}],
            "shareDevices": [{"returnValue": 1, "data": {"token": "fresh"}}],
        }
    )
    client = lumentree_api_client.LumentreeHttpApiClient(session)
    client.set_token("stale")
    client.set_reauth_device_id("DEV1")

    info = asyncio.run(client.get_device_info("DEV1"))

    assert info["deviceId"] == "DEV1"
    manage = [h for url, h in session.requests if url.endswith("deviceManage")]
    assert [h.get("Authorization") for h in manage] == ["stale", "fresh"]


def test_token_is_not_renewed_without_a_device_id(lumentree_api_client):
    from custom_components.lumentree.core.exceptions import AuthException

    session = _ScriptedSession({"deviceManage": [{"returnValue": 203, "msg": "token"}]})
    client = lumentree_api_client.LumentreeHttpApiClient(session)
    client.set_token("stale")

    with pytest.raises(AuthException):
        asyncio.run(client.get_device_info("DEV1"))
    assert len(session.requests) == 1
