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
* Slot identity.  A sample's position in ``tableValueInfo`` is the 5-minute
  slot it was reported for, and both the charge/discharge split and the hourly
  rollup have to key on that slot.  Dropping an unreadable entry and then
  working positionally slides every later sample one slot earlier, which books
  charge as discharge and files readings under the wrong hour.  This is the one
  a hole-free fixture cannot catch, so the fixtures here include holes.

The payload literals below are modelled on a capture from the real device
rather than invented, so the builders are pinned to a real shape; they do not
track the live server, and a shape change there will not fail these tests.
"""

from __future__ import annotations

import asyncio
import math

import pytest
from aiohttp import ServerConnectionError

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
        assert lumentree_api_client.LumentreeHttpApiClient._slot_readings(None) == []

    def test_each_sample_is_keyed_by_the_slot_it_was_reported_for(
        self, lumentree_api_client
    ) -> None:
        """A slot is the sample's position on the wire, holes included.

        An entry that cannot be read is dropped, not shifted: the 300 at wire
        index 2 stays at slot 2 rather than sliding to slot 1.  Every hour
        fold downstream reads the slot, so this is the identity the whole
        mapping rests on.
        """
        frame = lumentree_api_client.LumentreeHttpApiClient._slot_readings(
            {"tableValueInfo": [100, "x", 300]}
        )
        assert frame == [(0, 100.0), (2, 300.0)]

    def test_a_series_with_no_readable_entry_frames_as_empty(
        self, lumentree_api_client
    ) -> None:
        assert lumentree_api_client.LumentreeHttpApiClient._slot_readings(
            {"tableValueInfo": [None, "x", {}]}
        ) == []


class TestBatterySignConvention:
    def test_positive_charge_series_splits_into_charge_and_discharge(
        self, lumentree_api_client
    ) -> None:
        """Positive values are charge, negative are discharge.

        This is the convention entities/sensor.py reads.  If the builder
        inverted these, the charge and discharge sensors would swap.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [(0, 500.0), (1, -300.0), (2, 0.0)], 30.0, 12.0
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
            [(0, 100.0), (1, -100.0)], None, None
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
            [(0, 100.0), (1, -100.0)], None, None
        )
        assert built["battery_charge_series_hour_kwh"][0] > 0
        assert built["battery_discharge_series_hour_kwh"][0] > 0

    def test_unreported_slots_are_not_published_as_readings(
        self, lumentree_api_client
    ) -> None:
        """A slot nobody reported is not a reading, and must not become a 0 W one.

        Downstream (entities/sensor.py) publishes this list and turns it into
        kWh, so a hole written as 0.0 W is a chart point that claims the
        battery was idle at a moment the device said nothing about.  The frame
        simply has no entry for slot 1, so the flat list is two long -- and
        slot 2's -300 W still folds into hour 0, where it was reported.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [(0, 500.0), (2, -300.0)], None, None
        )
        assert built["battery_series_5min_w"] == [500.0, -300.0]
        assert built["battery_discharge_series_hour_kwh"][0] == pytest.approx(
            300 * (5 / 60) / 1000
        )

    def test_a_frame_with_no_reading_at_all_yields_no_series(self, lumentree_api_client) -> None:
        """An empty frame must not publish an empty series."""
        client = lumentree_api_client.LumentreeHttpApiClient
        assert "battery_series_5min_w" not in client._build_battery_result([], None, None)


class TestAllDayDataMapping:
    def _merged(self, api_client, payload):
        """Run a payload through the same merge the client uses."""
        return api_client.LumentreeHttpApiClient._merge_all_day_payload(payload)

    def test_totals_match_the_legacy_per_metric_endpoints(self, lumentree_api_client) -> None:
        """The combined endpoint must report the same totals, not merely similar ones.

        The PV, grid, load and essential totals were checked against the live
        comparison recorded in docs/probe_compare_day_endpoints.json, which
        marks those four ``match: true``.  The battery totals come from the
        constructed ``bat``/``batF`` literals in ``ALL_DAY_WITH_DISCHARGE`` and
        are **not** verified: that same file records ``bat.discharge`` as
        ``match: false`` with ``all_match: false``, and its caveat says the test
        device reports no battery, so the comparison cannot confirm the battery
        mapping.
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
        assert merged["battery_series_5min_w"] == [0.0, 0.0, 0.0, 0.0]

    def test_the_hour_fold_keeps_each_sample_in_its_own_hour(
        self, lumentree_api_client
    ) -> None:
        """The battery reproduction: a hole must not pull later readings back.

        `bat` reports a 500 W charge at slot 12 -- the first step of hour 1 --
        and cannot be read at slot 1.  Folding the flat list by array index put
        that charge in hour 0 and left hour 1 empty, because dropping the hole
        shortened the list.  The hour comes from the slot, so it lands in hour
        1 where it was actually reported.
        """
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 30, "tableValueInfo": [0, None] + [0.0] * 10 + [500.0]},
        })
        rollup = merged["battery_charge_series_hour_kwh"]
        assert rollup[0] == 0.0
        assert rollup[1] == pytest.approx(500 * (5 / 60) / 1000)
        # The flat list keeps only the readings that were sent.
        assert len(merged["battery_series_5min_w"]) == 12

    def test_the_pv_hour_fold_keeps_each_sample_in_its_own_hour(
        self, lumentree_api_client
    ) -> None:
        """The same reproduction on the PV metric, which has no battery path.

        PV goes straight from the payload to the fold, so if only the battery
        builder were slot-aware this is the one that would still be wrong.
        """
        merged = self._merged(lumentree_api_client, {
            "pv": {"tableValue": 60, "tableValueInfo": [0, None] + [0.0] * 10 + [500.0]},
        })
        assert merged["pv_series_hour_kwh"][0] == 0.0
        assert merged["pv_series_hour_kwh"][1] == pytest.approx(500 * (5 / 60) / 1000)

    def test_a_hole_free_series_folds_exactly_as_before(
        self, lumentree_api_client
    ) -> None:
        """Ordinary payloads must be untouched by the slot-aware fold.

        Every slot reported means slot == index for every sample, so the
        rollup has to equal the plain index-based arithmetic it replaced.
        """
        merged = self._merged(lumentree_api_client, ALL_DAY_WITH_DISCHARGE)
        step = (5 / 60) / 1000
        # pv [0, 0, 120, 240] all inside hour 0
        assert merged["pv_series_hour_kwh"][0] == pytest.approx(360 * step)
        assert merged["pv_sum_kwh"] == pytest.approx(360 * step)
        # bat [0, 500, 0, 0] / batF [0, 0, 300, 0]
        assert merged["battery_charge_series_hour_kwh"][0] == pytest.approx(500 * step)
        assert merged["battery_discharge_series_hour_kwh"][0] == pytest.approx(300 * step)


    def test_a_charge_only_day_publishes_a_full_discharge_rollup(
        self, lumentree_api_client
    ) -> None:
        """A day that only ever charged still has a discharge series -- of zeros.

        This is the documented no-discharge case: `bat` is present with the
        charge steps and `batF` is absent.  Both chart attributes have to carry
        24 entries, or the discharge chart renders blank instead of flat.
        """
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 30, "tableValueInfo": [0.0, 0.0, 300.0, 0.0]},
        })
        discharge = merged["battery_discharge_series_hour_kwh"]
        assert len(discharge) == 24
        assert sum(discharge) == 0.0
        assert merged["battery_charge_series_hour_kwh"][0] == pytest.approx(
            300 * (5 / 60) / 1000
        )

    def test_a_discharge_only_day_publishes_a_full_charge_rollup(
        self, lumentree_api_client
    ) -> None:
        """The mirror: an all-discharge frame still reports a 24-entry charge series.

        Reached from the legacy `getBatDayData` fallback, whose wire series is
        negated before it gets here, so a pure-discharge day arrives as a frame
        with no positive sample at all.
        """
        built = lumentree_api_client.LumentreeHttpApiClient._build_battery_result(
            [(0, -0.0), (1, -0.0), (2, -300.0), (3, -0.0)], None, None
        )
        charge = built["battery_charge_series_hour_kwh"]
        assert len(charge) == 24
        assert sum(charge) == 0.0
        assert built["battery_discharge_series_hour_kwh"][0] == pytest.approx(
            300 * (5 / 60) / 1000
        )

    def test_a_frame_with_no_battery_at_all_still_publishes_no_rollup(
        self, lumentree_api_client
    ) -> None:
        """The idle-side fix must not undo the absent-frame early-out.

        "This side was idle" and "there was no battery data" are different
        answers, and only the first one gets a zero-filled series.
        """
        merged = self._merged(lumentree_api_client, {
            "pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]},
        })
        assert "battery_charge_series_hour_kwh" not in merged
        assert "battery_discharge_series_hour_kwh" not in merged

    def test_battery_series_is_signed_charge_minus_discharge(self, lumentree_api_client) -> None:
        """Two unsigned series become one signed series, positive = charge."""
        merged = self._merged(lumentree_api_client, ALL_DAY_WITH_DISCHARGE)
        # bat=[0,500,0,0], batF=[0,0,300,0] => [0, +500, -300, 0]
        assert merged["battery_series_5min_w"] == [0.0, 500.0, -300.0, 0.0]

    def test_a_hole_in_one_series_does_not_shift_the_other_series(
        self, lumentree_api_client
    ) -> None:
        """The regression this mapping was rewritten for.

        An entry that cannot be read in `bat` used to shorten it by one, so
        every later charge sample slid one slot against `batF`.  The reported
        result was [100, 250, 0, 0]: the 300 W charge step was booked as
        discharge and the real 50 W discharge step disappeared.  Slot-signing
        gives [100, -50, 300, 0]: the hole is the only thing dropped, and the
        reported 0 at slot 3 is a reading, so it stays.
        """
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 30, "tableValueInfo": [100, None, 300, 0]},
            "batF": {"tableValue": 12, "tableValueInfo": [0, 50, 0, 0]},
        })
        assert merged["battery_series_5min_w"] == [100.0, -50.0, 300.0, 0.0]

    def test_a_hole_in_the_discharge_series_keeps_the_charge_series_aligned(
        self, lumentree_api_client
    ) -> None:
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 30, "tableValueInfo": [100, 300, 0, 200]},
            "batF": {"tableValue": 12, "tableValueInfo": [0, None, 50, 0]},
        })
        assert merged["battery_series_5min_w"] == [100.0, 300.0, -50.0, 200.0]

    def test_a_short_series_publishes_only_the_slots_it_reported(
        self, lumentree_api_client
    ) -> None:
        """A device that stopped publishing has not reported the rest of the day.

        Nothing is invented for the slots the series never reached, so a
        battery that went quiet at slot 2 does not draw a flat line at 0 W
        across the remainder of the chart.
        """
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 30, "tableValueInfo": [100, 300]},
            "batF": {"tableValue": 12, "tableValueInfo": [0, 50, None, None]},
        })
        assert merged["battery_series_5min_w"] == [100.0, 250.0]

    def test_no_battery_at_all_yields_no_series_and_no_discharge(
        self, lumentree_api_client
    ) -> None:
        """Neither metric present means no battery reading, not a battery at 0."""
        merged = self._merged(lumentree_api_client, {
            "pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]},
        })
        assert "battery_series_5min_w" not in merged
        assert "charge_today" not in merged
        assert "discharge_today" not in merged

    def test_a_battery_that_reported_nothing_still_publishes_no_series(
        self, lumentree_api_client
    ) -> None:
        """A present `bat` with no usable samples is the same answer as absent.

        The captured device reports `bat` with a 288-point series and a total
        of 0, so presence alone cannot mean "there is a series to draw".
        """
        merged = self._merged(lumentree_api_client, {
            "bat": {"tableValue": 0, "tableValueInfo": [None, "x", None]},
            "batF": {"tableValue": None, "tableValueInfo": []},
        })
        assert "battery_series_5min_w" not in merged
        assert merged["charge_today"] == 0.0
        assert merged["discharge_today"] == 0.0

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

    def test_a_non_finite_total_is_treated_as_absent(
        self, lumentree_api_client
    ) -> None:
        """NaN and Infinity survive float(), so they need a finiteness guard.

        json.loads accepts the bare NaN/Infinity literals, so a malformed or
        truncated vendor body reaches the helpers without raising.  None is
        what this code already means by "no usable reading"; NaN is not,
        because it survives every downstream guard -- `or 0.0`, an all-zero
        emptiness check -- and would be written into the year cache and summed
        into every aggregate derived from that year.
        """
        total = lumentree_api_client.LumentreeHttpApiClient._metric_total_kwh
        assert total({"tableValue": float("nan")}) is None
        assert total({"tableValue": float("inf")}) is None
        assert total({"tableValue": float("-inf")}) is None
        assert total({"tableValue": "nan"}) is None

        merged = self._merged(lumentree_api_client, {
            "pv": {"tableValue": float("nan"), "tableValueInfo": []},
        })
        assert "pv_today" not in merged, f"a non-finite total was published: {merged}"

    def test_a_non_finite_total_does_not_defeat_the_emptiness_check(
        self, lumentree_api_client
    ) -> None:
        """The merged dict must still read as "no data" once it is guarded.

        ``get_daily_stats`` treats an empty dict as "the endpoint had nothing",
        and the coordinator treats an all-zero day as empty too.  A NaN defeats
        the second check (NaN compares False against the threshold), so a
        guarded payload has to come back empty rather than merely NaN-free.
        """
        merged = self._merged(lumentree_api_client, {
            "pv": {"tableValue": float("inf"), "tableValueInfo": []},
            "grid": {"tableValue": float("-inf"), "tableValueInfo": []},
        })
        assert merged == {}, f"a non-finite payload was not treated as empty: {merged}"

    def test_a_non_finite_series_sample_becomes_a_hole(
        self, lumentree_api_client
    ) -> None:
        """An unreadable sample is a hole, exactly like one that raises.

        The series is published as an attribute rather than through the cache,
        but the same vendor body feeds it, and a single NaN would otherwise
        propagate through the sum and every hour bucket it lands in.
        """
        merged = self._merged(lumentree_api_client, {
            "pv": {
                "tableValue": 60,
                "tableValueInfo": [0.0, float("nan"), 300.0] + [0.0] * 9,
            },
        })
        # The hole keeps its slot, so 300 W stays at slot 2 -- hour 0.
        assert merged["pv_series_5min_w"] == [0.0, 300.0] + [0.0] * 9
        assert not any(math.isnan(v) for v in merged["pv_series_hour_kwh"])
        assert math.isfinite(merged["pv_sum_kwh"])
        assert merged["pv_series_hour_kwh"][0] == pytest.approx(300 * (5 / 60) / 1000)

    def test_a_non_finite_sample_in_the_battery_series_becomes_a_hole(
        self, lumentree_api_client
    ) -> None:
        """The battery frame has its own coercion path through the merge."""
        merged = self._merged(lumentree_api_client, {
            "bat": {
                "tableValue": 30,
                "tableValueInfo": [0.0, float("inf"), 300.0] + [0.0] * 9,
            },
        })
        assert merged["battery_series_5min_w"] == [0.0, 300.0] + [0.0] * 9
        assert not any(math.isnan(v) for v in merged["battery_charge_series_hour_kwh"])

    def test_an_absent_charge_side_is_normalised_like_an_absent_discharge_side(
        self, lumentree_api_client
    ) -> None:
        """The gate has to be symmetric, or the mirror case takes the other road.

        With batF present and bat absent, charge_today would stay None, the key
        would be dropped, and the coordinator's `or 0.0` would read it back as
        0.0 -- the same substituted zero the discharge direction replaces
        explicitly.  Both directions must agree in the dict they return.
        """
        merged = self._merged(lumentree_api_client, {
            "batF": {"tableValue": 12, "tableValueInfo": [0, 0, 300, 0]},
        })
        assert merged["charge_today"] == 0.0
        assert merged["discharge_today"] == 1.2


class TestLegacyBatteryPath:
    """The legacy signed series must keep behaving exactly as it did.

    ``getBatDayData`` is still the fallback and still answers days the
    combined endpoint cannot, so the frame rework in the combined merge must
    not have changed what this path publishes.
    """

    def test_the_legacy_signed_series_is_negated_and_kept_whole(
        self, lumentree_api_client
    ) -> None:
        """Positive on the wire means discharge; the sensor reads the opposite.

        The device is the authority here (docs/api/API_PROTOCOL.md), and the
        negation is what makes the charge and discharge sensors point at the
        right side.  The zeros are real reported steps, so they stay.
        """
        legacy = {
            "/lesvr/getPVDayData": {
                "returnValue": 1,
                "data": {"pv": {"tableValue": 60, "tableValueInfo": []}},
            },
            "/lesvr/getBatDayData": {
                "returnValue": 1,
                "data": {
                    "bats": [{"tableValue": 30}, {"tableValue": 12}],
                    "tableValueInfo": [500, -200, 0],
                },
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
        session = _make_stub_session(legacy)
        client = lumentree_api_client.LumentreeHttpApiClient(session=session)
        client.set_token("stub-token")

        result = asyncio.run(client._fetch_battery_data({"deviceId": "H240909079"}))

        assert result["battery_series_5min_w"] == [-500.0, 200.0, 0.0]
        assert result["charge_today"] == 3.0
        assert result["discharge_today"] == 1.2
        # The wire's +500 is a DISCHARGE, so it belongs to the discharge rollup;
        # the -200 is the charge at slot 1 and is reported as +200 W.
        assert result["battery_discharge_series_hour_kwh"][0] == pytest.approx(
            500 * (5 / 60) / 1000
        )
        assert result["battery_charge_series_hour_kwh"][0] == pytest.approx(
            200 * (5 / 60) / 1000
        )

    def test_a_non_finite_legacy_total_does_not_surface_nan(
        self, lumentree_api_client
    ) -> None:
        """The legacy totals need the same guard as the combined endpoint's.

        ``bats[0].tableValue`` is read straight off the wire by this path, and
        a non-finite value there would reach the coordinator exactly as a
        combined-endpoint one would -- through `or 0.0`, which NaN survives.
        """
        legacy = {
            "/lesvr/getBatDayData": {
                "returnValue": 1,
                "data": {
                    "bats": [{"tableValue": float("nan")}, {"tableValue": 12}],
                    "tableValueInfo": [],
                },
            },
        }
        session = _make_stub_session(legacy)
        client = lumentree_api_client.LumentreeHttpApiClient(session=session)
        client.set_token("stub-token")

        result = asyncio.run(client._fetch_battery_data({"deviceId": "H240909079"}))

        assert result["charge_today"] is None
        assert result["discharge_today"] == 1.2
        assert not any(
            math.isnan(v) for v in result.values() if isinstance(v, float)
        ), f"a non-finite legacy total reached the caller: {result}"


def _combined_payload() -> dict:
    """A combined payload with one usable metric, for the fallback tests."""
    return {"pv": {"tableValue": 60, "tableValueInfo": [0, 0, 120, 240]}}


def _make_stub_session(responses: dict):
    """A recording aiohttp-session stub answering by endpoint path.

    ``responses`` maps an endpoint path to the JSON body to answer it with, so
    the client's real ``_request`` path runs and the calls it makes are
    observable in ``session.calls``.  A path mapped to an exception instance
    raises it on entry instead, which is how a transport failure is staged;
    the attempt is recorded before the raise, so a retry is still countable.
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
            body = responses[self._path]
            if isinstance(body, BaseException):
                raise body
            return _Response(body)

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

    def test_a_missing_combined_endpoint_is_asked_for_only_once(self, lumentree_api_client) -> None:
        """998 means "no such endpoint on this host", so stop paying for it.

        Regression: the combined call was attempted on every poll, so a host
        without the endpoint cost one wasted request per poll forever and
        logged the fallback notice just as often.
        """
        responses = dict(self._LEGACY)
        responses["/lesvr/getAllDayData"] = {
            "returnValue": 998,
            "msg": "您访问对页面不存在",
        }
        client, session = self._client(lumentree_api_client, responses)

        first = asyncio.run(client.get_daily_stats("H240909079", "2026-09-11"))
        assert first["total_load_today"] == 17.0
        assert [c["path"] for c in session.calls] == [
            "/lesvr/getAllDayData",
            "/lesvr/getPVDayData",
            "/lesvr/getBatDayData",
            "/lesvr/getOtherDayData",
        ], f"first poll should probe the combined endpoint once: {session.calls}"

        del session.calls[:]
        second = asyncio.run(client.get_daily_stats("H240909079", "2026-09-12"))

        assert "/lesvr/getAllDayData" not in {c["path"] for c in session.calls}, (
            f"the absent endpoint was probed again: {session.calls}"
        )
        assert sorted(c["path"] for c in session.calls) == sorted(self._LEGACY), (
            f"the second poll should be the three legacy calls only: {session.calls}"
        )
        assert second["total_load_today"] == 17.0
        assert second["pv_today"] == 6.0

    def test_a_transport_error_leaves_the_combined_endpoint_in_the_retry_ladder(
        self, lumentree_api_client, monkeypatch
    ) -> None:
        """Only 998 is durable -- a dead connection says nothing about the host.

        The next poll must try the combined endpoint again, otherwise one
        dropped connection would silently demote the host to the three-call
        path for the life of the client.
        """
        for name in ("API_RETRY_BASE_DELAY", "API_RETRY_MAX_DELAY"):
            monkeypatch.setattr(lumentree_api_client, name, 0.0)

        responses = dict(self._LEGACY)
        responses["/lesvr/getAllDayData"] = ServerConnectionError("connection dropped")
        client, session = self._client(lumentree_api_client, responses)

        first = asyncio.run(client.get_daily_stats("H240909079", "2026-09-11"))
        assert first["total_load_today"] == 17.0
        assert client._all_day_data_absent is False, (
            "a transport failure must not be mistaken for a missing endpoint"
        )

        del session.calls[:]
        second = asyncio.run(client.get_daily_stats("H240909079", "2026-09-12"))

        assert "/lesvr/getAllDayData" in {c["path"] for c in session.calls}, (
            f"the combined endpoint was dropped from the retry ladder: {session.calls}"
        )
        assert second["total_load_today"] == 17.0


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
