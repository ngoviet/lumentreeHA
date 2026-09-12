"""update_daily has exactly one return shape; every caller must match it."""

from __future__ import annotations

import pytest


def test_update_daily_returns_a_pair(lumentree_cache) -> None:
    result = lumentree_cache.update_daily({}, "2026-01-01", {"pv": 1.0})
    assert isinstance(result, tuple)
    cache, month_index = result
    assert isinstance(cache, dict)
    assert month_index == 0


def test_three_value_unpack_raises(lumentree_cache) -> None:
    """Documents the crash at services/aggregator.py:479 before the fix."""
    with pytest.raises(ValueError):
        _c, _m, _extra = lumentree_cache.update_daily({}, "2026-01-01", {"pv": 1.0})
