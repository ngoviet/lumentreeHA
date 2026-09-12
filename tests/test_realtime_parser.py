"""Decode tests for core/realtime_parser.py.

Fixtures are built as CRC-valid Modbus-RTU frames rather than taken from the
captured corpus: ``mqtt_discovery.json`` stores payloads that were round-tripped
through a lossy UTF-8 decode, so almost none of them survive intact (see
tools/analyze_corpus.py).  Values chosen here are ones observed in real
captured frames, so the assertions encode real device behaviour.
"""

from __future__ import annotations

import pytest
from custom_components.lumentree.const import (
    KEY_AC_IN_CURRENT,
    KEY_AC_IN_FREQ,
    KEY_AC_IN_POWER,
    KEY_AC_OUT_CURRENT,
    KEY_AC_OUT_FREQ,
    KEY_AC_OUT_VOLTAGE,
    KEY_BATTERY_CAPACITY,
    KEY_BATTERY_CURRENT,
    KEY_BATTERY_MAX_CHARGE_CURRENT,
    KEY_BATTERY_SOC,
    KEY_BATTERY_VOLTAGE,
    KEY_DEVICE_TEMP,
    KEY_GRID_POWER,
    KEY_GRID_VOLTAGE,
    KEY_LOAD_POWER,
    KEY_PV1_VOLTAGE,
    KEY_TODAY_PV_KWH,
)

# Register indices the parser reads, mirrored here so a change to const.REG_ADDR
# that silently moves a signal shows up as a test failure rather than as wrong
# sensor data.
REG = {
    "FIRMWARE_VERSION": 2,
    "BATTERY_VOLTAGE": 11,
    "BATTERY_CURRENT": 12,
    "AC_OUT_VOLTAGE": 13,
    "GRID_VOLTAGE": 15,
    "AC_OUT_FREQ": 16,
    "AC_IN_FREQ": 17,
    "PV1_VOLTAGE": 20,
    "DEVICE_TEMP": 24,
    "TODAY_PV_INPUT": 33,
    "BATTERY_SOC": 50,
    "AC_IN_CURRENT": 54,
    "GRID_POWER": 59,
    "AC_OUT_CURRENT": 62,
    "LOAD_POWER": 67,
    "AC_IN_POWER": 53,
    "BATTERY_MAX_CHARGE_CURRENT": 106,
    "BATTERY_CAPACITY": 104,
}

SEPARATOR = "2b2b2b2b" * 1


def crc16(data: bytes) -> int:
    """Modbus CRC16, little-endian on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(registers: dict[int, int], n_regs: int = 151) -> str:
    """Build a CRC-valid 0x03 response payload with '++++' separator prefix.

    ``registers`` maps a register index to the raw unsigned word to place there.
    The default is the full 151-register frame (302 bytes), which is the only
    frame long enough to carry registers at index >= 95; a shorter frame makes
    those reads legitimately return nothing.

    The byte-count field is a single byte on the wire, so a 302-byte body
    declares 46 -- exactly what the captured corpus shows.
    """
    body = bytearray()
    for i in range(n_regs):
        word = registers.get(i, 0)
        body += (word & 0xFFFF).to_bytes(2, "big")
    pdu = bytes([0x01, 0x03, len(body) & 0xFF]) + bytes(body)
    crc = crc16(pdu)
    return SEPARATOR + (pdu + crc.to_bytes(2, "little")).hex()


class TestMainFrame:
    def test_decodes_core_measurements(self, lumentree_parser) -> None:
        frame = build_frame(
            {
                REG["BATTERY_VOLTAGE"]: 5150,   # 51.50 V
                REG["BATTERY_CURRENT"]: 40,     # 0.40 A
                REG["AC_OUT_VOLTAGE"]: 2320,    # 232.0 V
                REG["GRID_VOLTAGE"]: 2310,      # 231.0 V
                REG["AC_OUT_FREQ"]: 4970,       # 49.70 Hz
                REG["AC_IN_FREQ"]: 4960,        # 49.60 Hz
                REG["PV1_VOLTAGE"]: 281,        # raw volts
                REG["DEVICE_TEMP"]: 1374,       # (1374-1000)/10 = 37.4 C
                REG["BATTERY_SOC"]: 48,
            }
        )
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_BATTERY_VOLTAGE] == pytest.approx(51.5)
        assert data[KEY_BATTERY_CURRENT] == pytest.approx(-0.4)
        assert data[KEY_AC_OUT_VOLTAGE] == pytest.approx(232.0)
        assert data[KEY_GRID_VOLTAGE] == pytest.approx(231.0)
        assert data[KEY_AC_OUT_FREQ] == pytest.approx(49.7)
        assert data[KEY_AC_IN_FREQ] == pytest.approx(49.6)
        assert data[KEY_PV1_VOLTAGE] == pytest.approx(281.0)
        assert data[KEY_DEVICE_TEMP] == pytest.approx(37.4)
        assert data[KEY_BATTERY_SOC] == 48

    def test_ac_input_power_is_watts_not_centiwatts(self, lumentree_parser) -> None:
        """Register 53 is raw watts.

        The integration used to divide it by 100.  The vendor app reads it
        signed and labels the raw word "W", and captured frames agree: dividing
        by 100 makes the largest AC input power ever observed 3.15 W.
        """
        frame = build_frame({REG["AC_IN_POWER"]: 315})
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_AC_IN_POWER] == pytest.approx(315.0)

    def test_load_power_is_signed(self, lumentree_parser) -> None:
        """Load power is signed in the app; a negative word must stay negative."""
        frame = build_frame({REG["LOAD_POWER"]: 0xFFFF - 99})  # -100 as signed
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_LOAD_POWER] == pytest.approx(-100.0)

    def test_grid_power_is_signed(self, lumentree_parser) -> None:
        frame = build_frame({REG["GRID_POWER"]: 0xFFFF})  # -1
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_GRID_POWER] == pytest.approx(-1.0)


class TestExtendedRegisters:
    """Registers recovered from the vendor app's register table."""

    def test_decodes_charge_settings(self, lumentree_parser) -> None:
        frame = build_frame(
            {
                REG["TODAY_PV_INPUT"]: 34,          # 3.4 kWh
                REG["AC_IN_CURRENT"]: 90,           # 0.90 A
                REG["AC_OUT_CURRENT"]: 120,         # 1.20 A
                REG["BATTERY_MAX_CHARGE_CURRENT"]: 80,
                REG["BATTERY_CAPACITY"]: 300,       # 300 Ah
            }
        )
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_TODAY_PV_KWH] == pytest.approx(3.4)
        assert data[KEY_AC_IN_CURRENT] == pytest.approx(0.9)
        assert data[KEY_AC_OUT_CURRENT] == pytest.approx(1.2)
        assert data[KEY_BATTERY_MAX_CHARGE_CURRENT] == pytest.approx(80.0)
        assert data[KEY_BATTERY_CAPACITY] == pytest.approx(300.0)

    def test_charge_voltages_scale_by_100(self, lumentree_parser) -> None:
        from custom_components.lumentree.const import (
            KEY_BOOST_CHARGE_VOLTAGE,
            KEY_EQUALIZING_CHARGE_VOLTAGE,
            KEY_FLOAT_CHARGE_VOLTAGE,
        )

        frame = build_frame({101: 5700, 102: 5680, 103: 5520})
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_EQUALIZING_CHARGE_VOLTAGE] == pytest.approx(57.0)
        assert data[KEY_BOOST_CHARGE_VOLTAGE] == pytest.approx(56.8)
        assert data[KEY_FLOAT_CHARGE_VOLTAGE] == pytest.approx(55.2)

    def test_enum_registers_map_to_labels(self, lumentree_parser) -> None:
        from custom_components.lumentree.const import KEY_AI_MODE, KEY_CHARGE_FROM_AC, KEY_GRID_TYPE

        frame = build_frame({96: 2, 120: 1, 125: 4})
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_AI_MODE] == "Rainy"
        assert data[KEY_CHARGE_FROM_AC] == "On"
        assert data[KEY_GRID_TYPE] == "240V"

    def test_unknown_enum_value_is_reported_not_dropped(self, lumentree_parser) -> None:
        from custom_components.lumentree.const import KEY_AI_MODE

        frame = build_frame({96: 99})
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_AI_MODE] == "Unknown (99)"


class TestShortFrames:
    """The 190-byte frame most units return stops at register 94."""

    def test_registers_beyond_frame_are_absent_not_wrong(self, lumentree_parser) -> None:
        frame = build_frame({REG["BATTERY_SOC"]: 50}, n_regs=95)
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_BATTERY_SOC] == 50
        # Registers at index >= 95 cannot be read from this frame.
        assert KEY_BATTERY_CAPACITY not in data
        assert KEY_BATTERY_MAX_CHARGE_CURRENT not in data

    def test_legacy_frame_with_trailing_metadata(self, lumentree_parser) -> None:
        """A 202-byte body is the 95-register frame plus 12 bytes of metadata."""
        body = bytearray()
        for i in range(95):
            body += (5150 if i == REG["BATTERY_VOLTAGE"] else 0).to_bytes(2, "big")
        body += b"\x00" * 12
        pdu = bytes([0x01, 0x03, len(body) & 0xFF]) + bytes(body)
        frame = SEPARATOR + (pdu + crc16(pdu).to_bytes(2, "little")).hex()
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_BATTERY_VOLTAGE] == pytest.approx(51.5)

    def test_full_frame_declares_a_wrapped_byte_count(self, lumentree_parser) -> None:
        """A 302-byte body declares 46, not 302.

        The byte count is one byte on the wire, so the parser must dispatch on
        the real length.  It used to compare the declared count against 302,
        which could never be true: every full frame fell through to the
        "unrecognized length" warning and was only rescued by a fallback.
        """
        frame = build_frame({REG["BATTERY_VOLTAGE"]: 5150, REG["BATTERY_SOC"]: 48})
        assert int(frame[len(SEPARATOR) + 4 : len(SEPARATOR) + 6], 16) == 302 & 0xFF
        data = lumentree_parser.parse_mqtt_payload(frame)
        assert data is not None
        assert data[KEY_BATTERY_VOLTAGE] == pytest.approx(51.5)
        assert data[KEY_BATTERY_SOC] == 48

    def test_full_frame_logs_no_warning(self, lumentree_parser, caplog) -> None:
        """A well-formed full frame must not trip the length warnings."""
        import logging

        frame = build_frame({REG["BATTERY_SOC"]: 48})
        with caplog.at_level(logging.WARNING):
            lumentree_parser.parse_mqtt_payload(frame)
        noisy = [
            r
            for r in caplog.records
            if "Unrecognized length" in r.getMessage() or "mismatch" in r.getMessage()
        ]
        assert noisy == [], [r.getMessage() for r in noisy]


class TestFailureModes:
    def test_empty_payload_returns_none(self, lumentree_parser) -> None:
        assert lumentree_parser.parse_mqtt_payload("") is None

    def test_non_frame_payload_returns_none(self, lumentree_parser) -> None:
        assert lumentree_parser.parse_mqtt_payload("deadbeef") is None

    def test_bad_crc_returns_none(self, lumentree_parser) -> None:
        frame = build_frame({REG["BATTERY_SOC"]: 50})
        corrupted = frame[:-2] + ("00" if frame[-2:] != "00" else "01")
        assert lumentree_parser.parse_mqtt_payload(corrupted) is None

    def test_odd_length_hex_returns_none(self, lumentree_parser) -> None:
        assert lumentree_parser.parse_mqtt_payload(SEPARATOR + "0103abc") is None

    def test_modbus_exception_response_returns_none(self, lumentree_parser) -> None:
        """A 2-byte body is an exception response, not data."""
        pdu = bytes([0x01, 0x03, 0x02, 0x00, 0x00])
        frame = SEPARATOR + (pdu + crc16(pdu).to_bytes(2, "little")).hex()
        assert lumentree_parser.parse_mqtt_payload(frame) is None


class TestCommandGeneration:
    def test_generated_command_has_valid_crc(self, lumentree_parser) -> None:
        cmd = lumentree_parser.generate_modbus_read_command(1, 3, 0, 151)
        assert cmd is not None
        raw = bytes.fromhex(cmd)
        assert raw[0] == 1 and raw[1] == 3
        assert raw[2:4] == (0).to_bytes(2, "big")
        assert raw[4:6] == (151).to_bytes(2, "big")
        expected = crc16(raw[:-2])
        assert raw[-2:] == expected.to_bytes(2, "little")
