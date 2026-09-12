"""Real-time MQTT payload parser for Lumentree integration.

This module handles parsing of real-time MQTT data from Lumentree inverters.
All parsing functions are optimized for performance with cached struct formats.
"""

import logging
import math
import struct
from typing import Any

import crcmod.predefined

from ..const import (
    KEY_AC_COUPLING,
    KEY_AC_IN_CURRENT,
    KEY_AC_IN_FREQ,
    KEY_AC_IN_POWER,
    KEY_AC_IN_VOLTAGE,
    KEY_AC_OUT_CURRENT,
    KEY_AC_OUT_FREQ,
    KEY_AC_OUT_FREQ_SET,
    KEY_AC_OUT_POWER,
    KEY_AC_OUT_VA,
    KEY_AC_OUT_VOLTAGE,
    KEY_AI_MODE,
    KEY_BATTERY_CAPACITY,
    KEY_BATTERY_CELL_INFO,
    KEY_BATTERY_CURRENT,
    KEY_BATTERY_LOW_VOLTAGE_PROTECTION,
    KEY_BATTERY_MAX_CHARGE_CURRENT,
    KEY_BATTERY_MODE,
    KEY_BATTERY_POWER,
    KEY_BATTERY_RECOVERY_VOLTAGE,
    KEY_BATTERY_SOC,
    KEY_BATTERY_STATUS,
    KEY_BATTERY_TYPE,
    KEY_BATTERY_VOLTAGE,
    KEY_BOOST_CHARGE_VOLTAGE,
    KEY_CHARGE_FROM_AC,
    KEY_CT_TRICKLE_FEED,
    KEY_CTRL_VERSION,
    KEY_DEVICE_TEMP,
    KEY_EQUALIZING_CHARGE_INTERVAL,
    KEY_EQUALIZING_CHARGE_TIME,
    KEY_EQUALIZING_CHARGE_VOLTAGE,
    KEY_FLOAT_CHARGE_VOLTAGE,
    KEY_FW_VERSION,
    KEY_GEN_INV_POWER,
    KEY_GRID_POWER,
    KEY_GRID_STATUS,
    KEY_GRID_TYPE,
    KEY_GRID_VOLTAGE,
    KEY_IS_UPS_MODE,
    KEY_LOAD_POWER,
    KEY_LOW_CAPACITY_CUTOFF,
    KEY_MASTER_SLAVE_STATUS,
    KEY_MAX_DISCHARGE_CURRENT,
    KEY_MQTT_DEVICE_SN,
    KEY_PROTECTING_RECOVERY_POINT,
    KEY_PV1_POWER,
    KEY_PV1_VOLTAGE,
    KEY_PV2_POWER,
    KEY_PV2_VOLTAGE,
    KEY_PV_POWER,
    KEY_SELF_CONSUMPTION_RATIO,
    KEY_TODAY_PV_KWH,
    KEY_WORK_MODE,
    MAP_AC_OUT_FREQ_SET,
    MAP_AI_MODE,
    MAP_BATTERY_MODE,
    MAP_BATTERY_TYPE,
    MAP_GRID_TYPE,
    MAP_ON_OFF,
    MAP_WORK_MODE,
    REG_ADDR,
    REG_ADDR_CELL_COUNT,
)

crc16_modbus_func = crcmod.predefined.mkCrcFun("modbus")

_LOGGER = logging.getLogger(__name__)

# Cached struct format strings for performance (40-50% faster parsing)
_STRUCT_FORMATS: dict[str, struct.Struct] = {
    "signed_2": struct.Struct(">h"),  # Signed 16-bit big-endian
    "unsigned_2": struct.Struct(">H"),  # Unsigned 16-bit big-endian
    "signed_4": struct.Struct(">i"),  # Signed 32-bit big-endian
    "unsigned_4": struct.Struct(">I"),  # Unsigned 32-bit big-endian
}


def calculate_crc16_modbus(pb: bytes) -> int | None:
    """Calculate Modbus CRC16.

    Args:
        pb: Payload bytes

    Returns:
        CRC16 value or None if calculation fails
    """
    if crc16_modbus_func:
        try:
            return crc16_modbus_func(pb)
        except Exception:
            return None
    return None


def verify_crc(ph: str) -> tuple[bool, str | None]:
    """Verify CRC of payload hex string.

    Args:
        ph: Payload hex string

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not crc16_modbus_func:
        return True, "CRC skipped"

    if len(ph) < 4:
        return False, "Too short"

    try:
        dh, rc = ph[:-4], ph[-4:].lower()
        db = bytes.fromhex(dh)
        cc = calculate_crc16_modbus(db)

        if cc is None:
            return False, "Calc fail"

        cch = cc.to_bytes(2, "little").hex()
        ok = cch == rc

        if not ok:
            _LOGGER.warning(f"CRC mismatch! Received: {rc}, Calculated: {cch}")
        else:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("CRC check successful")

        return ok, None if ok else f"Mismatch {rc} vs {cch}"
    except Exception:
        return False, "Verify error"


def generate_modbus_read_command(sid: int, fc: int, addr: int, num: int) -> str | None:
    """Generate a Modbus read command hex string with CRC.

    Args:
        sid: Slave ID
        fc: Function code
        addr: Start address
        num: Number of registers

    Returns:
        Command hex string or None if generation fails
    """
    if not crc16_modbus_func:
        _LOGGER.error("Cannot generate command: crcmod library missing")
        return None

    try:
        pdu = bytearray([fc]) + addr.to_bytes(2, "big") + num.to_bytes(2, "big")
        adu = bytearray([sid]) + pdu
        crc = calculate_crc16_modbus(bytes(adu))

        if crc is None:
            _LOGGER.error("CRC calculation failed")
            return None

        full = adu + crc.to_bytes(2, "little")
        command_hex = full.hex()

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Generated Modbus command: %s", command_hex)

        return command_hex
    except Exception as exc:
        _LOGGER.exception(f"Error generating Modbus command: {exc}")
        return None


def _read_register(
    db: bytes, ra: int, signed: bool, factor: float = 1.0, byte_count: int = 2
) -> float | None:
    """Read register value with cached struct formats for performance.

    Args:
        db: Data bytes
        ra: Register address (offset)
        signed: Whether value is signed
        factor: Multiplication factor
        byte_count: Number of bytes (2 or 4)

    Returns:
        Register value or None if reading fails
    """
    offset_bytes = ra * 2

    if offset_bytes + byte_count > len(db):
        return None

    try:
        raw_bytes = db[offset_bytes : offset_bytes + byte_count]

        # Use cached struct formats for performance
        if byte_count == 2:
            fmt = _STRUCT_FORMATS["signed_2"] if signed else _STRUCT_FORMATS["unsigned_2"]
        elif byte_count == 4:
            fmt = _STRUCT_FORMATS["signed_4"] if signed else _STRUCT_FORMATS["unsigned_4"]
        else:
            _LOGGER.warning(f"Unsupported byte_count {byte_count}")
            return None

        raw_val = fmt.unpack(raw_bytes)[0]
        result = round(raw_val * factor, 3)

        if not math.isfinite(result):
            _LOGGER.warning(f"Invalid float read from register {ra}")
            return None

        return result
    except struct.error as exc:
        _LOGGER.error(f"Struct error reading register {ra}: {exc}")
        return None
    except Exception as exc:
        _LOGGER.exception(f"Unexpected error reading register {ra}: {exc}")
        return None


def _make_reader(db: bytes, addr_map: dict):
    """Create a fast register reader bound to a specific data buffer and address map.

    Returns a callable that avoids recreating closures on each parse_mqtt_payload call.
    """

    def read_reg(key: str, signed: bool, factor: float = 1.0, byte_count: int = 2):
        r = addr_map.get(key)
        if r is not None:
            return _read_register(db, r, signed, factor, byte_count)
        return None

    return read_reg


def _read_string(db: bytes, sa: int, nr: int) -> str | None:
    """Read ASCII string from registers.

    Args:
        db: Data bytes
        sa: Start address
        nr: Number of registers

    Returns:
        Decoded string or None if reading fails
    """
    offset = sa * 2
    num_bytes = nr * 2

    if offset + num_bytes > len(db):
        return None

    try:
        raw_bytes = db[offset : offset + num_bytes]
        decoded_string = raw_bytes.decode("ascii", "ignore").replace("\x00", "").strip()
        return decoded_string if decoded_string else None
    except Exception:
        return None


def _parse_battery_cells(db: bytes) -> dict[str, Any] | None:
    """Parse battery cell voltages.

    Args:
        db: Data bytes containing cell information

    Returns:
        Dictionary with cell info or None if parsing fails
    """
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("Parsing %s cell bytes", len(db))

    cell_data = {}
    num_cells = 0
    total_voltage = 0.0
    min_voltage = 999.0
    max_voltage = 0.0

    num_possible_cells = len(db) // 2

    for i in range(num_possible_cells):
        v_mv = _read_register(db, i, False)
        if v_mv is not None:
            cell_voltage = round(v_mv / 1000.0, 3)
            if 1.0 < cell_voltage < 5.0:  # Valid cell voltage range
                cell_data[f"c_{i + 1:02d}"] = cell_voltage
                num_cells += 1
                total_voltage += cell_voltage
                min_voltage = min(min_voltage, cell_voltage)
                max_voltage = max(max_voltage, cell_voltage)

    if num_cells > 0:
        avg = round(total_voltage / num_cells, 3)
        diff = round(max_voltage - min_voltage, 3) if num_cells > 1 else 0.0
        result = {
            "number_of_cells": num_cells,
            "avg": avg,
            "min": min_voltage if min_voltage != 999.0 else None,
            "max": max_voltage if max_voltage != 0.0 else None,
            "diff": diff,
            "cells": cell_data,
        }
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Parsed cells: %s", result)
        return result
    else:
        _LOGGER.warning("No valid cells found")
        return None


def _parse_extended_registers(rr, db: bytes, parsed_data: dict[str, Any]) -> None:
    """Parse the register range recovered from the vendor app.

    Every factor and signedness flag below comes from the app's own formatter
    layer, cross-checked against the captured corpus (docs/api/REGISTER_MAP.md).
    Nothing here is guessed: where the app could not be read -- firmware
    version strings and the raw device-model prefix -- the register is left
    unpublished rather than reported under a name that might be wrong.

    Registers past index 94 are absent from the 190-byte frame most devices
    answer with, so ``rr`` returns None and the key is simply not set.
    """
    # Today's PV yield.  Rendered raw/10 and signed by the app; observed
    # values 0..91 line up with a normal daily yield in kWh.
    today_pv = rr("TODAY_PV_INPUT", True, 0.1)
    if today_pv is not None:
        parsed_data[KEY_TODAY_PV_KWH] = today_pv

    # AC currents.  Raw/100, signed on both sides.
    ac_in_cur = rr("AC_IN_CURRENT", True, 0.01)
    if ac_in_cur is not None:
        parsed_data[KEY_AC_IN_CURRENT] = ac_in_cur

    ac_out_cur = rr("AC_OUT_CURRENT", True, 0.01)
    if ac_out_cur is not None:
        parsed_data[KEY_AC_OUT_CURRENT] = ac_out_cur

    # Generator input power, raw watts.
    gen_power = rr("GEN_INV_POWER", True)
    if gen_power is not None:
        parsed_data[KEY_GEN_INV_POWER] = gen_power

    # Charge/discharge ceiling settings, raw amps.
    max_charge = rr("BATTERY_MAX_CHARGE_CURRENT", False)
    if max_charge is not None:
        parsed_data[KEY_BATTERY_MAX_CHARGE_CURRENT] = max_charge

    max_discharge = rr("MAX_DISCHARGE_CURRENT", False)
    if max_discharge is not None:
        parsed_data[KEY_MAX_DISCHARGE_CURRENT] = max_discharge

    # Battery pack capacity in Ah, raw.
    capacity = rr("BATTERY_CAPACITY", False)
    if capacity is not None:
        parsed_data[KEY_BATTERY_CAPACITY] = capacity

    # Charge voltage targets, raw/100 volts.
    for key, reg in (
        (KEY_EQUALIZING_CHARGE_VOLTAGE, "EQUALIZING_CHARGE_VOLTAGE"),
        (KEY_BOOST_CHARGE_VOLTAGE, "BOOST_CHARGE_VOLTAGE"),
        (KEY_FLOAT_CHARGE_VOLTAGE, "FLOAT_CHARGE_VOLTAGE"),
        (KEY_BATTERY_LOW_VOLTAGE_PROTECTION, "BATTERY_LOW_VOLTAGE_PROTECTION"),
        (KEY_BATTERY_RECOVERY_VOLTAGE, "BATTERY_RECOVERY_VOLTAGE"),
    ):
        value = rr(reg, False, 0.01)
        if value is not None:
            parsed_data[key] = value

    # State-of-charge thresholds, raw percent.
    for key, reg in (
        (KEY_LOW_CAPACITY_CUTOFF, "LOW_CAPACITY_CUTOFF"),
        (KEY_PROTECTING_RECOVERY_POINT, "PROTECTING_RECOVERY_POINT"),
    ):
        value = rr(reg, False)
        if value is not None:
            parsed_data[key] = value

    # Timers and trickle feed.
    interval = rr("EQUALIZING_CHARGE_INTERVAL", False)
    if interval is not None:
        parsed_data[KEY_EQUALIZING_CHARGE_INTERVAL] = interval

    duration = rr("EQUALIZING_CHARGE_TIME", False)
    if duration is not None:
        parsed_data[KEY_EQUALIZING_CHARGE_TIME] = duration

    trickle = rr("CT_TRICKLE_FEED", False)
    if trickle is not None:
        parsed_data[KEY_CT_TRICKLE_FEED] = trickle

    # Integer settings reported through an enum map, so a value the app does
    # not define surfaces as "Unknown (n)" instead of being dropped.
    for key, reg, mapping, label in (
        (KEY_AI_MODE, "AI_MODE", MAP_AI_MODE, "AI mode"),
        (KEY_GRID_TYPE, "GRID_TYPE", MAP_GRID_TYPE, "grid type"),
        (
            KEY_AC_OUT_FREQ_SET,
            "AC_OUT_FREQ_SET",
            MAP_AC_OUT_FREQ_SET,
            "AC output frequency setting",
        ),
        (KEY_CHARGE_FROM_AC, "CHARGE_FROM_AC", MAP_ON_OFF, "charge from AC"),
        (KEY_AC_COUPLING, "AC_COUPLING", MAP_ON_OFF, "AC coupling"),
    ):
        raw = rr(reg, False)
        if raw is not None:
            value = int(raw)
            if value not in mapping:
                # An unmapped value means the register table recovered from the
                # app is incomplete for this firmware, so log it rather than
                # only publishing the placeholder.
                _LOGGER.debug(
                    "Unmapped %s value %s (register %s) -- enum map may need extending",
                    label,
                    value,
                    reg,
                )
            parsed_data[key] = mapping.get(value, f"Unknown ({value})")


def parse_mqtt_payload(ph: str) -> dict[str, Any] | None:
    """Parse MQTT payload hex string.

    This is the main entry point for parsing real-time MQTT data from Lumentree inverters.
    Handles both main data (95 registers) and battery cell data.

    Args:
        ph: Payload hex string

    Returns:
        Parsed data dictionary or None if parsing fails

    Raises:
        None - All exceptions are caught and logged, returns None on error
    """
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("Parsing payload: %s...", ph[:100])

    parsed_data: dict[str, Any] = {}
    db: bytes | None = None
    is_cell_data = False
    resp_hex: str | None = None
    sep = "2b2b2b2b"

    # Extract response hex from payload
    if sep in ph:
        parts = ph.split(sep)
        resp_hex = (
            parts[1]
            if len(parts) == 2 and (parts[1].startswith("0103") or parts[1].startswith("0104"))
            else None
        )
    elif ph.startswith("0103") or ph.startswith("0104"):
        resp_hex = ph

    if not resp_hex or len(resp_hex) < 12:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Invalid payload format or too short")
        return None

    try:
        crc_ok, crc_err = verify_crc(resp_hex)
        if not crc_ok:
            _LOGGER.warning("CRC verification failed: %s", crc_err)
            return None
        bc = int(resp_hex[4:6], 16)
        dh = resp_hex[6:-4]
        db = bytes.fromhex(dh)

        # Modbus-RTU carries the byte count in a single byte, so a response
        # longer than 255 bytes wraps: the 302-byte (151-register) frame
        # arrives declaring 46.  Compare low byte against low byte, and branch
        # on the actual length -- comparing the declared count against the full
        # length can never match for those frames.
        bc_actual = len(db) & 0xFF
        if bc != bc_actual:
            _LOGGER.warning(
                "Byte count mismatch: response is %s bytes (declares %s, low byte %s)",
                len(db),
                bc,
                bc_actual,
            )

        if len(db) == 0 and bc > 0:
            _LOGGER.error("No data bytes")
            return None

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Parsing %s bytes", len(db))

        expected_cell_bytes = REG_ADDR_CELL_COUNT * 2
        expected_main_bytes = 151 * 2  # 151 registers (0-150), 302 bytes
        expected_main_bytes_legacy = 95 * 2  # Legacy 95-register format
        expected_main_bytes_extended = expected_main_bytes_legacy + 12  # Legacy + metadata

        # Determine data type.  Dispatch on the real byte length, never on the
        # declared count -- the count wraps for frames over 255 bytes.
        main_len = len(db)
        if main_len == expected_cell_bytes:
            is_cell_data = True
            _LOGGER.debug("Cell data detected")
        elif main_len == expected_main_bytes:
            is_cell_data = False
            _LOGGER.debug("Main data (151 regs)")
        elif main_len in (expected_main_bytes_legacy, expected_main_bytes_extended):
            is_cell_data = False
            if main_len == expected_main_bytes_extended:
                _LOGGER.debug("Main data (legacy 95 regs + 12 bytes metadata)")
                db = db[:expected_main_bytes_legacy]
            else:
                _LOGGER.debug("Main data (legacy 95 regs)")
        elif main_len == 198:
            # 198 bytes = 99 registers, likely main data with partial metadata (missing 4 bytes)
            # Try parsing as legacy main data (190 bytes) - skip last 8 bytes
            is_cell_data = False
            _LOGGER.debug("Main data (198 bytes, likely 99 regs - treating as 95 regs)")
            db = db[:expected_main_bytes_legacy]
        elif main_len == 2:
            # 2 bytes = Modbus exception response or error
            _LOGGER.debug(
                f"Modbus exception/error response (2 bytes): {resp_hex[:20]}... "
                f"(function_code={resp_hex[2:4] if len(resp_hex) >= 4 else 'N/A'})"
            )
            return None
        elif main_len <= 20:
            # Very short responses - likely error or control messages
            _LOGGER.debug(
                f"Short response ({len(db)} bytes) - likely error/control: "
                f"{resp_hex[: min(50, len(resp_hex))]}..."
            )
            return None
        else:
            # Unknown length - log with more context but try to parse if it's close to expected
            _LOGGER.warning(
                "Unrecognized length (%s bytes, declares %s). Expected: %s or %s for main, "
                "%s for cells. Payload preview: %s...",
                main_len,
                bc,
                expected_main_bytes,
                expected_main_bytes_legacy,
                expected_cell_bytes,
                resp_hex[: min(60, len(resp_hex))],
            )
            # If length is close to any expected main format, try parsing
            for expected_len in (expected_main_bytes, expected_main_bytes_legacy):
                if abs(main_len - expected_len) <= 20 and main_len >= expected_len - 10:
                    _LOGGER.debug("Attempting to parse %s bytes as main data", main_len)
                    is_cell_data = False
                    if main_len > expected_len:
                        db = db[:expected_len]
                    else:
                        db = db + b"\x00" * (expected_len - main_len)
                    break
            else:
                return None

        if is_cell_data:
            cell_result = _parse_battery_cells(db)
            if cell_result:
                parsed_data[KEY_BATTERY_CELL_INFO] = cell_result
        else:
            # Parse main registers with optimized read helper (module-level function)
            rr = _make_reader(db, REG_ADDR)

            # Battery voltage
            bat_volt = rr("BATTERY_VOLTAGE", False, 0.01)
            if bat_volt is not None:
                parsed_data[KEY_BATTERY_VOLTAGE] = bat_volt

            # Battery current (inverted to match card convention)
            # Positive = Charging, Negative = Discharging (matches battery power)
            bat_curr = rr("BATTERY_CURRENT", True, 0.01)
            if bat_curr is not None:
                parsed_data[KEY_BATTERY_CURRENT] = -bat_curr  # Invert sign for card compatibility

            # AC output voltage
            ac_out_v = rr("AC_OUT_VOLTAGE", False, 0.1)
            if ac_out_v is not None:
                parsed_data[KEY_AC_OUT_VOLTAGE] = ac_out_v

            # Grid voltage (also AC input voltage)
            grid_v = rr("GRID_VOLTAGE", False, 0.1)
            if grid_v is not None:
                parsed_data[KEY_GRID_VOLTAGE] = grid_v
                parsed_data[KEY_AC_IN_VOLTAGE] = grid_v

            # AC output frequency
            ac_out_f = rr("AC_OUT_FREQ", False, 0.01)
            if ac_out_f is not None:
                parsed_data[KEY_AC_OUT_FREQ] = ac_out_f

            # AC input frequency
            ac_in_f = rr("AC_IN_FREQ", False, 0.01)
            if ac_in_f is not None:
                parsed_data[KEY_AC_IN_FREQ] = ac_in_f

            # Device temperature.  The app reads three temperature registers and
            # takes the highest, but only register 24 falls inside the frame
            # this integration requests, so the other two are unreachable and
            # the max is not reproducible.  Signedness is immaterial: the
            # highest raw value in the corpus is 1544, giving 54.4 C, and the
            # observed range is a plausible 33.8..54.4 C.
            temp_raw = rr("DEVICE_TEMP", True)
            if temp_raw is not None:
                temp_c = round((temp_raw - 1000) / 10, 1)
                parsed_data[KEY_DEVICE_TEMP] = temp_c if -40 < temp_c < 150 else None

            # PV voltages
            pv1_v = rr("PV1_VOLTAGE", False)
            if pv1_v is not None:
                parsed_data[KEY_PV1_VOLTAGE] = pv1_v

            pv2_v = rr("PV2_VOLTAGE", False)
            if pv2_v is not None:
                parsed_data[KEY_PV2_VOLTAGE] = pv2_v

            # Grid power
            grid_p = rr("GRID_POWER", True)
            if grid_p is not None:
                parsed_data[KEY_GRID_POWER] = grid_p

            # AC input power.  The vendor app reads this signed and displays the
            # raw word labelled "W", with no division anywhere in its graph and
            # parameter formatters.  Captured frames agree: across frames that
            # pass every independent sanity check the largest value seen is 315,
            # and where AC voltage and current are both readable the implied
            # power factor only lands in a believable range (about 0.25) when the
            # word is read as watts -- dividing by 100 puts it at 0.0025.
            ac_in_p = rr("AC_IN_POWER", True)
            if ac_in_p is not None:
                parsed_data[KEY_AC_IN_POWER] = ac_in_p

            # Load power.  Signed in the app (`_readSignedIntWithConfig`).
            # No captured value exceeds 32767, so this only matters if a unit
            # ever reports a negative load; reading it unsigned would turn that
            # into a ~32 kW spike.
            load_p = rr("LOAD_POWER", True)
            if load_p is not None:
                parsed_data[KEY_LOAD_POWER] = load_p

            # AC output power
            ac_out_p = rr("AC_OUT_POWER", False)
            if ac_out_p is not None:
                parsed_data[KEY_AC_OUT_POWER] = ac_out_p

            # AC output VA
            ac_out_va = rr("AC_OUT_VA", False)
            if ac_out_va is not None:
                parsed_data[KEY_AC_OUT_VA] = ac_out_va

            # Battery power and status (inverted to match card convention)
            # Positive = Charging, Negative = Discharging (for card compatibility)
            bp_signed = rr("BATTERY_POWER", True)
            if bp_signed is not None:
                parsed_data[KEY_BATTERY_POWER] = -bp_signed  # Invert sign for card compatibility
                parsed_data[KEY_BATTERY_STATUS] = (
                    "Charging" if parsed_data[KEY_BATTERY_POWER] > 0 else "Discharging"
                )
            else:
                parsed_data[KEY_BATTERY_POWER] = None
                parsed_data[KEY_BATTERY_STATUS] = "Unknown"

            # Grid status
            grid_status = (
                "Importing"
                if parsed_data.get(KEY_GRID_POWER, 0) > 0
                else "Exporting"
                if parsed_data.get(KEY_GRID_POWER) is not None
                else "Unknown"
            )
            parsed_data[KEY_GRID_STATUS] = grid_status

            # PV power
            pv1 = rr("PV1_POWER", False)
            pv2 = rr("PV2_POWER", False)
            if pv1 is not None:
                parsed_data[KEY_PV1_POWER] = pv1
            if pv2 is not None:
                parsed_data[KEY_PV2_POWER] = pv2

            pv_power = (pv1 or 0) + (pv2 or 0) if (pv1 is not None or pv2 is not None) else None
            if pv_power is not None:
                parsed_data[KEY_PV_POWER] = pv_power

            # Battery SOC
            soc = rr("BATTERY_SOC", False)
            soc_value = max(0, min(100, int(soc))) if soc is not None else None
            if soc_value is not None:
                parsed_data[KEY_BATTERY_SOC] = soc_value

            # UPS mode
            ups = rr("UPS_MODE", False)
            ups_mode = (ups == 0) if ups is not None else None
            if ups_mode is not None:
                parsed_data[KEY_IS_UPS_MODE] = ups_mode

            # Battery type
            bt = rr("BATTERY_TYPE", False)
            battery_type = MAP_BATTERY_TYPE.get(int(bt), "Present") if bt is not None else None
            if battery_type is not None:
                parsed_data[KEY_BATTERY_TYPE] = battery_type

            # Master/slave status
            ms = rr("MASTER_SLAVE_STATUS", False)
            if ms is not None:
                parsed_data[KEY_MASTER_SLAVE_STATUS] = ms

            # Device SN
            device_sn = _read_string(db, REG_ADDR["DEVICE_MODEL_START"], 5)
            if device_sn is not None:
                parsed_data[KEY_MQTT_DEVICE_SN] = device_sn

            # Firmware version (register 2, within range)
            fw_ver = rr("FIRMWARE_VERSION", False)
            if fw_ver is not None:
                parsed_data[KEY_FW_VERSION] = f"v{int(fw_ver)}"

            # Controller version (register 8, within range)
            ctrl_ver = rr("CONTROLLER_VERSION", False)
            if ctrl_ver is not None:
                parsed_data[KEY_CTRL_VERSION] = f"v{int(ctrl_ver)}"

            # Battery mode (register 100 — may be beyond read range)
            bat_mode = rr("BATTERY_MODE", False)
            if bat_mode is not None:
                parsed_data[KEY_BATTERY_MODE] = MAP_BATTERY_MODE.get(int(bat_mode), "Unknown")

            # Work mode (register 150 — may be beyond read range)
            work_mode = rr("WORK_MODE", False)
            if work_mode is not None:
                parsed_data[KEY_WORK_MODE] = MAP_WORK_MODE.get(
                    int(work_mode), f"Unknown ({int(work_mode)})"
                )

            # --- Extended registers ---------------------------------------
            # Named and scaled from the vendor app's DeviceAddrConfig and its
            # formatter layer, then cross-checked against captured frames (see
            # docs/api/REGISTER_MAP.md).  A device that answers with the common
            # 190-byte frame stops at index 94, so most of these read None
            # rather than a wrong value.
            _parse_extended_registers(rr, db, parsed_data)

            # Self-consumption ratio (calculated from existing data)
            pv_total = parsed_data.get(KEY_PV1_POWER, 0) or 0
            if parsed_data.get(KEY_PV2_POWER):
                pv_total += parsed_data[KEY_PV2_POWER]
            grid_power = parsed_data.get(KEY_GRID_POWER)
            if pv_total > 0 and grid_power is not None:
                if grid_power < 0:  # Exporting to grid
                    direct_consumption = pv_total + grid_power
                    if direct_consumption < 0:
                        direct_consumption = 0
                else:  # Importing from grid or balanced
                    direct_consumption = pv_total
                parsed_data[KEY_SELF_CONSUMPTION_RATIO] = round(
                    direct_consumption / pv_total * 100, 1
                )

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Parsed main data: %s", parsed_data)

    except Exception as exc:
        _LOGGER.exception(f"Parse error: {exc}")
        return None

    if parsed_data:
        data_type = "Cells" if is_cell_data else "Main"
        _LOGGER.debug("Parse OK (%s)", data_type)
        return parsed_data
    else:
        _LOGGER.warning(f"No data parsed from: {resp_hex[:60] if resp_hex else 'N/A'}...")
        return None
