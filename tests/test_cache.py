"""Round-trip tests for services/cache.py.

The cache is the store behind every daily/monthly/yearly/total statistics
sensor, and the service handlers in ``__init__.py`` read and write it from the
Home Assistant event loop.  These tests exercise the real file I/O against a
temporary directory -- no Home Assistant, no mocking of the store itself -- so
that a change to how often aggregates are recomputed shows up here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

KEY_PV = "pv"
KEY_GRID = "grid"
KEY_LOAD = "load"
KEY_ESSENTIAL = "essential"
KEY_CHARGE = "charge"
KEY_DISCHARGE = "discharge"


@pytest.fixture
def cache_dir(lumentree_cache, tmp_path: Path, monkeypatch) -> Path:
    """Point the module's cache root at a temporary directory."""
    monkeypatch.setattr(lumentree_cache, "CACHE_BASE_DIR", str(tmp_path))
    return tmp_path


class TestRoundTrip:
    def test_save_then_load_returns_the_same_daily_values(self, lumentree_cache, cache_dir) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(
            cache,
            "2026-03-04",
            {KEY_PV: 12.3, KEY_GRID: 4.5, KEY_LOAD: 9.0, KEY_ESSENTIAL: 2.0},
        )
        lumentree_cache.save_year("dev1", 2026, cache)

        loaded = lumentree_cache.load_year("dev1", 2026, auto_recompute=False)
        assert loaded["daily"]["2026-03-04"]["pv"] == pytest.approx(12.3)
        assert loaded["daily"]["2026-03-04"]["grid"] == pytest.approx(4.5)

    def test_load_of_missing_year_returns_an_empty_cache(self, lumentree_cache, cache_dir) -> None:
        loaded = lumentree_cache.load_year("never-written", 1999)
        assert loaded["daily"] == {}
        assert len(loaded["monthly"]["pv"]) == 12
        assert loaded["yearly_total"]["pv"] == 0.0

    def test_update_daily_accumulates_into_the_right_month(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        for day, pv in (("2026-01-10", 1.0), ("2026-03-02", 5.0), ("2026-03-20", 2.5)):
            lumentree_cache.update_daily(cache, day, {KEY_PV: pv})

        assert cache["monthly"]["pv"][0] == pytest.approx(1.0)  # January
        assert cache["monthly"]["pv"][2] == pytest.approx(7.5)  # March
        assert cache["yearly_total"]["pv"] == pytest.approx(8.5)

    def test_re_updating_a_day_replaces_rather_than_adds(self, lumentree_cache, cache_dir) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-05-01", {KEY_PV: 3.0})
        lumentree_cache.update_daily(cache, "2026-05-01", {KEY_PV: 7.0})

        assert cache["daily"]["2026-05-01"]["pv"] == pytest.approx(7.0)
        assert cache["monthly"]["pv"][4] == pytest.approx(7.0)
        assert cache["yearly_total"]["pv"] == pytest.approx(7.0)

    def test_saved_kwh_is_total_load_minus_grid_never_negative(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(
            cache,
            "2026-06-01",
            {KEY_LOAD: 10.0, KEY_ESSENTIAL: 2.0, KEY_GRID: 4.0},
        )
        entry = cache["daily"]["2026-06-01"]
        assert entry["total_load"] == pytest.approx(12.0)
        assert entry["saved_kwh"] == pytest.approx(8.0)

        # A day that imports more than it uses must not report negative savings.
        lumentree_cache.update_daily(
            cache,
            "2026-06-02",
            {KEY_LOAD: 1.0, KEY_ESSENTIAL: 0.0, KEY_GRID: 5.0},
        )
        assert cache["daily"]["2026-06-02"]["saved_kwh"] == pytest.approx(0.0)


class TestRecomputeIsConsistent:
    def test_recompute_reproduces_the_incremental_aggregates(
        self, lumentree_cache, cache_dir
    ) -> None:
        """The O(1) path and the full rebuild must agree.

        ``update_daily`` maintains the month buckets incrementally while
        ``recompute_aggregates`` rebuilds them from the daily map.  Any drift
        between the two is a wrong sensor value, so they are compared directly.
        """
        incremental = lumentree_cache._empty_cache()
        days = {
            "2026-01-15": {KEY_PV: 2.0, KEY_GRID: 1.0, KEY_LOAD: 4.0, KEY_ESSENTIAL: 1.0},
            "2026-01-16": {KEY_PV: 8.0, KEY_GRID: 0.0, KEY_LOAD: 3.0, KEY_ESSENTIAL: 0.5},
            "2026-07-01": {KEY_PV: 5.5, KEY_GRID: 2.5, KEY_LOAD: 6.0, KEY_ESSENTIAL: 1.5},
            "2026-12-31": {KEY_PV: 0.0, KEY_GRID: 3.0, KEY_LOAD: 3.0, KEY_ESSENTIAL: 0.0},
        }
        for day, values in days.items():
            lumentree_cache.update_daily(incremental, day, values)

        rebuilt = lumentree_cache.recompute_aggregates(
            {"daily": incremental["daily"], "monthly": {}, "yearly_total": {}}
        )

        assert rebuilt["monthly"] == incremental["monthly"]
        assert rebuilt["yearly_total"] == incremental["yearly_total"]

    def test_recompute_is_idempotent(self, lumentree_cache, cache_dir) -> None:
        cache = lumentree_cache._empty_cache()
        for day, pv in (("2026-02-01", 3.0), ("2026-02-28", 4.0), ("2026-09-09", 1.0)):
            lumentree_cache.update_daily(cache, day, {KEY_PV: pv})

        once = lumentree_cache.recompute_aggregates(cache)
        snapshot = json.loads(json.dumps(once))
        twice = lumentree_cache.recompute_aggregates(once)

        assert twice["monthly"] == snapshot["monthly"]
        assert twice["yearly_total"] == snapshot["yearly_total"]

    def test_load_year_auto_recompute_repairs_a_corrupt_monthly_array(
        self, lumentree_cache, cache_dir
    ) -> None:
        """Monthly buckets that drifted are rebuilt from the daily map on load.

        ``_needs_recompute`` triggers when the first eleven months all hold the
        same non-zero value, which is the signature of a cache written in
        "every month equals the current month" style.
        """
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-04-05", {KEY_PV: 6.0})
        cache["monthly"]["pv"] = [5.0] * 12
        lumentree_cache.save_year("dev2", 2026, cache)

        repaired = lumentree_cache.load_year("dev2", 2026, auto_recompute=True)
        assert repaired["monthly"]["pv"][3] == pytest.approx(6.0)
        assert repaired["monthly"]["pv"][0] == pytest.approx(0.0)

    def test_load_year_does_not_recompute_an_all_zero_cache(
        self, lumentree_cache, cache_dir
    ) -> None:
        """An all-zero month array is the legitimate "no data yet" state.

        ``_needs_recompute`` deliberately does not fire on it, so loading a
        freshly created cache does not write the file back.
        """
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-04-05", {KEY_PV: 6.0})
        cache["monthly"] = {k: lumentree_cache._empty_month() for k in cache["monthly"]}
        lumentree_cache.save_year("dev3", 2026, cache)

        loaded = lumentree_cache.load_year("dev3", 2026, auto_recompute=True)
        assert loaded["monthly"]["pv"][3] == pytest.approx(0.0)

    def test_load_year_without_auto_recompute_leaves_the_cache_alone(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-04-05", {KEY_PV: 6.0})
        cache["monthly"]["pv"] = [5.0] * 12
        lumentree_cache.save_year("dev4", 2026, cache)

        untouched = lumentree_cache.load_year("dev4", 2026, auto_recompute=False)
        assert untouched["monthly"]["pv"][3] == pytest.approx(5.0)


class TestSummaries:
    def test_summarize_month_and_year_agree_with_the_daily_map(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-08-01", {KEY_PV: 4.0, KEY_CHARGE: 1.0})
        lumentree_cache.update_daily(cache, "2026-08-02", {KEY_PV: 6.0, KEY_CHARGE: 2.0})

        month = lumentree_cache.summarize_month(cache, 8)
        assert month["pv"] == pytest.approx(10.0)
        assert month["charge"] == pytest.approx(3.0)

        year = lumentree_cache.summarize_year(cache)
        assert year["pv"] == pytest.approx(10.0)
        assert year["charge"] == pytest.approx(3.0)

    def test_mark_empty_records_the_date_and_update_daily_clears_it(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.mark_empty(cache, "2026-01-01")
        lumentree_cache.mark_empty(cache, "2026-01-02")
        assert cache["meta"]["empty_dates"] == ["2026-01-01", "2026-01-02"]

        lumentree_cache.update_daily(cache, "2026-01-01", {KEY_PV: 1.0})
        assert cache["meta"]["empty_dates"] == ["2026-01-02"]


class TestDurability:
    def test_purge_year_removes_the_file_and_frees_the_year(
        self, lumentree_cache, cache_dir
    ) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-01-01", {KEY_PV: 1.0})
        lumentree_cache.save_year("dev4", 2026, cache)
        assert Path(lumentree_cache.cache_path("dev4", 2026)).exists()

        assert lumentree_cache.purge_year("dev4", 2026) is True
        assert not Path(lumentree_cache.cache_path("dev4", 2026)).exists()
        assert lumentree_cache.load_year("dev4", 2026)["daily"] == {}

    def test_purge_year_on_a_missing_file_reports_false(self, lumentree_cache, cache_dir) -> None:
        assert lumentree_cache.purge_year("dev5", 1990) is False

    def test_a_corrupt_file_falls_back_to_the_backup(self, lumentree_cache, cache_dir) -> None:
        cache = lumentree_cache._empty_cache()
        lumentree_cache.update_daily(cache, "2026-02-02", {KEY_PV: 5.0})
        lumentree_cache.save_year("dev6", 2026, cache)

        path = Path(lumentree_cache.cache_path("dev6", 2026))
        path.replace(path.with_suffix(".json.bak"))
        path.write_text("{ not json", encoding="utf-8")

        restored = lumentree_cache.load_year("dev6", 2026, auto_recompute=False)
        assert restored["daily"]["2026-02-02"]["pv"] == pytest.approx(5.0)

    def test_a_corrupt_file_without_a_backup_reports_empty(
        self, lumentree_cache, cache_dir
    ) -> None:
        path = Path(lumentree_cache.cache_path("dev7", 2026))
        path.write_text("{ not json", encoding="utf-8")
        assert lumentree_cache.load_year("dev7", 2026)["daily"] == {}
