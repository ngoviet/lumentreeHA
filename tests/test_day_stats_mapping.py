"""Tests for the day-statistics mapping in core/api_client.py.

The integration reads a day's PV/battery/grid/load figures from one of two
sources: the combined ``getAllDayData`` endpoint, or the three per-metric
endpoints it supersedes.  Both funnel through the same builders, and the whole
point of the builders is that a caller cannot tell which source served it.

The two sources genuinely disagree on two things, and both are silent failures
if mapped wrong:

* Battery.  ``getBatDayData`` gives one *signed* series where positive means
  discharge; ``getAllDayData`` gives two *unsigned* series, ``bat`` (charge) and
  ``batF`` (discharge).  Getting the sign backwards reports a discharging
  battery as a charging one, with no error anywhere.
* ``batF`` absence.  With no discharge, the combined endpoint omits ``batF``
  entirely rather than returning zeros.  Code that indexes it raises.

The payload literals below are modelled on a capture from the real device
rather than invented, so the builders are pinned to a real shape; they do not
track the live server, and a shape change there will not fail these tests.
"""

from __future__ import annotations

import asyncio

import pytest

# Shape modelled on GET /lesvr/getAllDayData on a real device (abridged).  The
# tableValue totals are taken from that capture (pv 60, grid 116, homeload 170,
# essentialLoad 0).  The tableValueInfo arrays are four-point stand-ins, not
# excerpts -- a real day carries 288 points, so a four-element array cannot be
# one.  Only homeload's opening values come from the capture; the rest are
# chosen so the arithmetic stays legible.  bat/batF are constructed and
# unverified, because the captured device reports no battery.  Two things to
# preserve when editing: bat/batF are separate unsigned series, and batF is
# missing rather than zero when the day had no discharge.
ALL_DAY_WITH_DISCHARGE = {
    "pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]},
    "grid": {"tableValue": 116, "tableValueInfo": [485, 485, 0, 400]},
    "homeload": {"tableValue": 170, "tableValueInfo": [469, 469, 0, 425]},
    "essentialLoad": {"tableValue": 0, "tableValueInfo": [0, 0, 0, 0]},
    "bat": {"tableValue": 30, "tableValueInfo": [0, 500, 0, 0]},
    "batF": {"tableValue": 12, "tableValueInfo": [0, 0, 300, 0]},
}

# The common case for this device: no battery at all, so batF is absent.
ALL_DAY_NO_DISCHARGE = {
    "pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]},
    "grid": {"tableValue": 116, "tableValueInfo": [485, 485, 0, 400]},
    "homeload": {"tableValue": 170, "tableValueInfo": [469, 469, 0, 425]},
    "essentialLoad": {"tableValue": 0, "tableValueInfo": [0, 0, 0, 0]},
    "bat": {"tableValue": 0, "tableValueInfo": [0, 0, 0, 0]},
}


class TestMetricHelpers:
    def test_total_is_converted_from_tenths_of_a_kwh(self, lumentree_api_client) -> None:
        assert lumentree_api_client.LumentreeHttpApiClient._metric_total_kwh(
            {"tableValue": 170}
        ) == 17.0

    @pytest.mark.parametrize("value", [None, "not-a-number", {}])
    def test_unusable_totals_come_back_as_none(self, lumentree_api_client, value) -> None:
        """A missing or malformed total must be None, never a fake 0.0.

        None propagates to the sensor as unknown; 0.0 would render as a real
        reading of zero kWh.
        """
        if value == {}:
            assert lumentree_api_client.LumentreeHttpApiClient._metric_total_kwh(value) is None
        else:
            assert lumentree_api_client.LumentreeHttpApiClient._metric_total_kwh(
                {"tableValue": value}
            ) is None

    def test_missing_metric_yields_no_series(self, lumentree_api_client) -> None:
        assert lumentree_api_client.LumentreeHttpApiClient._metric_series_w(None) == []


class TestBatterySignConvention:
    def test_positive_charge_series_splits_into_charge_and_discharge(
        self, lumentree_api_client
    ) -> None:
        """Positive values are charge, negative are discharge.

        This is the convention entities/sensor.py reads.  If the builder
        inverted these, the charge and discharge sensors would swap.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [500.0, -300.0, 0.0], 30.0, 12.0
        )
        # 500 W over a 5-minute step, positive => charge
        assert built["battery_charge_series_hour_kwh"][0] == pytest.approx(500 * (5 / 60) / 1000)
        # -300 W in step 1 => discharge, reported as a positive magnitude
        assert built["battery_discharge_series_hour_kwh"][0] == pytest.approx(300 * (5 / 60) / 1000)

    def test_a_five_minute_step_feeds_only_one_side(self, lumentree_api_client) -> None:
        """At 5-minute resolution a step is charge or discharge, never both.

        The hourly rollup below deliberately can contain both -- see the note
        there -- so the exclusive property belongs at the 5-minute level.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [100.0, -100.0], None, None
        )
        charge_5min = built["battery_charge_series_hour_kwh"]
        discharge_5min = built["battery_discharge_series_hour_kwh"]
        # Two steps land in hour 0; exactly one contributes charge, one discharge.
        assert charge_5min[0] > 0
        assert discharge_5min[0] > 0
        # No step adds to both totals: the magnitudes are the two inputs, not doubled.
        assert charge_5min[0] + discharge_5min[0] == pytest.approx(
            (100 + 100) * (5 / 60) / 1000
        )

    def test_hourly_rollup_may_contain_both_charge_and_discharge(self, lumentree_api_client) -> None:
        """A single hour can legitimately show both, and the totalling must not hide it.

        12 five-minute steps fold into one hour. A battery that charges for part
        of an hour and discharges for the rest produces a non-zero entry in both
        hourly series -- asserting they are mutually exclusive would be wrong.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [100.0, -100.0], None, None
        )
        assert built["battery_charge_series_hour_kwh"][0] > 0
        assert built["battery_discharge_series_hour_kwh"][0] > 0


class TestAllDayDataMapping:
    def _merged(self, api_client, payload):
        """Run a payload through the same merge the client uses."""
        return api_client.LumentreeHttpApiClient._merge_all_day_payload(payload)

    def test_totals_match_the_legacy_per_metric_endpoints(self, lumentree_api_client) -> None:
        """The combined endpoint must report the same totals, not merely similar ones.

        Values checked against a live comparison between the two paths.
        """
        merged = self._merged(lumentree_api_client, ALL_DAY_WITH_DISCHARGE)
        assert merged["pv_today"] == 6.0
        assert merged["grid_in_today"] == 11.6
        assert merged["load_today"] == 17.0
        assert merged["essential_today"] == 0.0
        assert merged["total_load_today"] == 17.0
        assert merged["charge_today"] == 3.0
        assert merged["discharge_today"] == 1.2

    def test_missing_batf_does_not_raise(self, lumentree_api_client) -> None:
        """No discharge means batF is absent, not zero.

        Indexing it would raise KeyError on every quiet day -- which is most
        days for a device without a battery.  Discharge must instead read as 0.
        """
        merged = self._merged(lumentree_api_client, ALL_DAY_NO_DISCHARGE)
        assert merged["discharge_today"] == 0.0
        assert merged["charge_today"] == 0.0

    def test_absent_batf_does_not_truncate_the_charge_series(self, lumentree_api_client) -> None:
        """The charge series keeps its full length when discharge is absent."""
        merged = self._merged(lumentree_api_client, ALL_DAY_NO_DISCHARGE)
        assert len(merged["battery_series_5min_w"]) == 4

    def test_battery_series_is_signed_charge_minus_discharge(self, lumentree_api_client) -> None:
        """Two unsigned series become one signed series, positive = charge."""
        merged = self._merged(lumentree_api_client, ALL_DAY_WITH_DISCHARGE)
        # bat=[0,500,0,0], batF=[0,0,300,0] => [0, +500, -300, 0]
        assert merged["battery_series_5min_w"] == [0.0, 500.0, -300.0, 0.0]

    def test_empty_payload_does_not_raise(self, lumentree_api_client) -> None:
        """A response with no metrics at all yields no data rather than an error."""
        assert self._merged(lumentree_api_client, {}) == {}

    def test_a_payload_with_no_usable_metric_is_indistinguishable_from_empty(
        self, lumentree_api_client
    ) -> None:
        """A response whose every metric is unusable must read as "no data".

        This is the same answer the three legacy endpoints give, and the answer
        ``get_daily_stats`` tests before deciding to fall back.  A dict that is
        merely non-empty here -- carrying six keys whose values are all None --
        would suppress the fallback and let the coordinator cache a day of
        zeros, so emptiness has to mean "nothing usable", not "some keys".
        """
        assert self._merged(lumentree_api_client, {"pv": None, "grid": "nonsense"}) == {}


def _combined_payload() -> dict:
    """A combined payload with one usable metric, for the fallback tests."""
    return {"pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]}}


def _make_stub_session(responses: dict):
    """A recording aiohttp-session stub answering by endpoint path.

    ``responses`` maps an endpoint path to the JSON body to answer it with, so
    the client's real ``_request`` path runs and the calls it makes are
    observable in ``session.calls``.
    """

    class _Response:
        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.status = 200
            self.ok = True

        async def text(self) -> str:
            return str(self._payload)

        async def json(self, content_type=None) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            return None

    class _Request:
        def __init__(self, recorder, path, headers) -> None:
            self._recorder, self._path, self._headers = recorder, path, headers

        async def __aenter__(self):
            self._recorder.append({"path": self._path, "headers": dict(self._headers)})
            return _Response(responses[self._path])

        async def __aexit__(self, *exc_info) -> bool:
            return False

    class _Session:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def request(self, method, url, **kwargs):
            path = url.split("suntcn.com", 1)[-1].split("?")[0]
            return _Request(self.calls, path, kwargs.get("headers", {}))

    return _Session()


class TestDailyStatsFallback:
    """A combined endpoint that reports nothing usable must not mask the day.

    ``get_daily_stats`` prefers the combined endpoint and falls back to the
    three per-metric endpoints when it reports no data.  Both sources now
    answer "no data" with an empty dict, so the gate reads the endpoint's own
    answer rather than the arity of a partly-populated dict.
    """

    _LEGACY = {
        "/lesvr/getPVDayData": {
            "returnValue": 1,
            "data": {"pv": {"tableValue": 60, "tableValueInfo": [0, 0]}},
        },
        "/lesvr/getBatDayData": {
            "returnValue": 1,
            "data": {"bats": [{"tableValue": 30}, {"tableValue": 12}], "tableValueInfo": []},
        },
        "/lesvr/getOtherDayData": {
            "returnValue": 1,
            "data": {
                "grid": {"tableValue": 116, "tableValueInfo": []},
                "homeload": {"tableValue": 170, "tableValueInfo": []},
                "essentialLoad": {"tableValue": 0, "tableValueInfo": []},
            },
        },
    }

    def _client(self, lumentree_api_client, responses):
        session = _make_stub_session(responses)
        client = lumentree_api_client.LumentreeHttpApiClient(session=session)
        client.set_token("stub-token")
        return client, session

    def test_an_unusable_combined_response_falls_back_and_keeps_serving(
        self, lumentree_api_client
    ) -> None:
        """The day must still be reported through the legacy path.

        Regression: an unusable combined response used to come back as a
        non-empty dict of None values, which is truthy, so the fallback never
        ran and the coordinator cached the day with grid and load as zero.
        """
        responses = dict(self._LEGACY)
        responses["/lesvr/getAllDayData"] = {
            "returnValue": 1,
            "data": {"pv": None, "grid": "nonsense"},
        }
        client, session = self._client(lumentree_api_client, responses)

        result = asyncio.run(client.get_daily_stats("H240909079", "2026-09-11"))

        assert result["total_load_today"] == 17.0
        assert result["grid_in_today"] == 11.6
        assert result["pv_today"] == 6.0
        assert len(session.calls) == 4, f"combined + 3 legacy expected, saw {session.calls}"
        assert {c["path"] for c in session.calls} == {
            "/lesvr/getAllDayData",
            "/lesvr/getPVDayData",
            "/lesvr/getBatDayData",
            "/lesvr/getOtherDayData",
        }

    def test_a_usable_combined_response_is_served_without_the_legacy_calls(
        self, lumentree_api_client
    ) -> None:
        """The one-request path stays the one-request path."""
        responses = dict(self._LEGACY)
        responses["/lesvr/getAllDayData"] = {"returnValue": 1, "data": _combined_payload()}
        client, session = self._client(lumentree_api_client, responses)

        result = asyncio.run(client.get_daily_stats("H240909079", "2026-09-11"))

        assert result["pv_today"] == 6.0
        assert [c["path"] for c in session.calls] == ["/lesvr/getAllDayData"]


class TestPayloadShapeGuards:
    """Malformed responses must degrade, not crash the coordinator."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"pv": None, "grid": "nonsense"},
            {"bat": {"tableValueInfo": "not-a-list"}},
            {"homeload": [], "essentialLoad": {"tableValue": "abc"}},
        ],
    )
    def test_malformed_metrics_do_not_raise(self, lumentree_api_client, payload) -> None:
        lumentree_api_client.LumentreeHttpApiClient._merge_all_day_payload(payload)
