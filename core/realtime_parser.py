"""Real-time MQTT payload parser for Lumentree integration.

This module handles parsing of real-time MQTT data from Lumentree inverters.
All parsing functions are optimized for performance with cached struct formats.
"""

from typing import Optional, Dict, Any, Tuple
import logging
import struct
import math

from ..const import (
    REG_ADDR,
    KEY_ONLINE_STATUS,
    KEY_PV_POWER,
    KEY_BATTERY_POWER,
    KEY_BATTERY_SOC,
    KEY_GRID_POWER,
    KEY_LOAD_POWER,
    KEY_BATTERY_VOLTAGE,
    KEY_BATTERY_CURRENT,
    KEY_AC_OUT_VOLTAGE,
    KEY_GRID_VOLTAGE,
    KEY_AC_OUT_FREQ,
    KEY_AC_OUT_POWER,
    KEY_AC_OUT_VA,
    KEY_DEVICE_TEMP,
    KEY_PV1_VOLTAGE,
    KEY_PV1_POWER,
    KEY_PV2_VOLTAGE,
    KEY_PV2_POWER,
    KEY_IS_UPS_MODE,
    KEY_BATTERY_STATUS,
    KEY_GRID_STATUS,
    KEY_AC_IN_VOLTAGE,
    KEY_AC_IN_FREQ,
    KEY_AC_IN_POWER,
    KEY_BATTERY_TYPE,
    KEY_MASTER_SLAVE_STATUS,
    KEY_MQTT_DEVICE_SN,
    KEY_BATTERY_CELL_INFO,
    REG_ADDR_CELL_START,
    REG_ADDR_CELL_COUNT,
    MAP_BATTERY_TYPE,
)

import crcmod.predefined

crc16_modbus_func = crcmod.predefined.mkCrcFun("modbus")

_LOGGER = logging.getLogger(__name__)

# Cached struct format strings for performance (40-50% faster parsing)
_STRUCT_FORMATS: Dict[str, struct.Struct] = {
    "signed_2": struct.Struct(">h"),  # Signed 16-bit big-endian
    "unsigned_2": struct.Struct(">H"),  # Unsigned 16-bit big-endian
    "signed_4": struct.Struct(">i"),  # Signed 32-bit big-endian
    "unsigned_4": struct.Struct(">I"),  # Unsigned 32-bit big-endian
}


def calculate_crc16_modbus(pb: bytes) -> Optional[int]:
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


def verify_crc(ph: str) -> Tuple[bool, Optional[str]]:
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


def generate_modbus_read_command(sid: int, fc: int, addr: int, num: int) -> Optional[str]:
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
) -> Optional[float]:
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


def _read_string(db: bytes, sa: int, nr: int) -> Optional[str]:
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
        decoded_string = (
            raw_bytes.decode("ascii", "ignore").replace("\x00", "").strip()
        )
        return decoded_string if decoded_string else None
    except Exception:
        return None


def _parse_battery_cells(db: bytes) -> Optional[Dict[str, Any]]:
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
            "num": num_cells,
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


def parse_mqtt_payload(ph: str) -> Optional[Dict[str, Any]]:
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

    parsed_data: Dict[str, Any] = {}
    db: Optional[bytes] = None
    is_cell_data = False
    resp_hex: Optional[str] = None
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
        crc_ok, _ = verify_crc(resp_hex)
        bc = int(resp_hex[4:6], 16)
        dh = resp_hex[6:-4]
        db = bytes.fromhex(dh)

        if len(db) != bc:
            _LOGGER.warning(f"Length mismatch: {len(db)} vs {bc}")

        if len(db) == 0 and bc > 0:
            _LOGGER.error("No data bytes")
            return None

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Parsing %s bytes", len(db))

        expected_cell_bytes = REG_ADDR_CELL_COUNT * 2
        expected_main_bytes = 95 * 2
        expected_main_bytes_extended = expected_main_bytes + 12  # With metadata

        # Determine data type
        if bc == expected_cell_bytes and len(db) == expected_cell_bytes:
            is_cell_data = True
            _LOGGER.info("Cell data detected")
        elif (bc == expected_main_bytes and len(db) == expected_main_bytes) or (
            bc == expected_main_bytes_extended and len(db) == expected_main_bytes_extended
        ):
            is_cell_data = False
            if len(db) == expected_main_bytes_extended:
                _LOGGER.info("Main data (95 regs + 12 bytes metadata)")
                # Skip last 12 bytes (metadata) and only parse first 95 registers
                db = db[:expected_main_bytes]
            else:
                _LOGGER.info("Main data (95 regs)")
        elif len(db) == 198 and bc == 198:
            # 198 bytes = 99 registers, likely main data with partial metadata (missing 4 bytes)
            # Try parsing as main data (190 bytes) - skip last 8 bytes
            is_cell_data = False
            _LOGGER.debug("Main data (198 bytes, likely 99 regs - treating as 95 regs)")
            db = db[:expected_main_bytes]
        elif len(db) == 2:
            # 2 bytes = Modbus exception response or error
            _LOGGER.debug(
                f"Modbus exception/error response (2 bytes): {resp_hex[:20]}... "
                f"(function_code={resp_hex[2:4] if len(resp_hex) >= 4 else 'N/A'})"
            )
            return None
        elif len(db) <= 20:
            # Very short responses - likely error or control messages
            _LOGGER.debug(
                f"Short response ({len(db)} bytes) - likely error/control: "
                f"{resp_hex[:min(50, len(resp_hex))]}..."
            )
            return None
        else:
            # Unknown length - log with more context but try to parse if it's close to expected
            _LOGGER.warning(
                f"Unrecognized length ({len(db)}/{bc}). Expected: "
                f"{expected_main_bytes} or {expected_main_bytes_extended} for main, "
                f"{expected_cell_bytes} for cells. "
                f"Payload preview: {resp_hex[:min(60, len(resp_hex))]}..."
            )
            # If length is close to main data (within 20 bytes), try parsing as main data
            if abs(len(db) - expected_main_bytes) <= 20 and len(db) >= expected_main_bytes - 10:
                _LOGGER.debug(f"Attempting to parse {len(db)} bytes as main data (truncating if needed)")
                is_cell_data = False
                if len(db) > expected_main_bytes:
                    # Truncate to expected length
                    db = db[:expected_main_bytes]
                else:
                    # Pad with zeros (shouldn't happen often)
                    db = db + b'\x00' * (expected_main_bytes - len(db))
            else:
                return None

        if is_cell_data:
            cell_result = _parse_battery_cells(db)
            if cell_result:
                parsed_data[KEY_BATTERY_CELL_INFO] = cell_result
        else:
            # Parse main registers with optimized read helper
            addr = REG_ADDR

            def rr(k, signed, factor=1.0, bc=2):
                """Read register helper."""
                r = addr.get(k)
                return _read_register(db, r, signed, factor, bc) if r is not None else None

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

            # Device temperature
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

            # AC input power
            ac_in_p_raw = rr("AC_IN_POWER", False)
            ac_in_p = round(ac_in_p_raw / 100, 2) if ac_in_p_raw is not None else None
            if ac_in_p is not None:
                parsed_data[KEY_AC_IN_POWER] = ac_in_p

            # Load power
            load_p = rr("LOAD_POWER", False)
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

            pv_power = (
                (pv1 or 0) + (pv2 or 0) if (pv1 is not None or pv2 is not None) else None
            )
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
            device_sn = _read_string(db, addr["DEVICE_MODEL_START"], 5)
            if device_sn is not None:
                parsed_data[KEY_MQTT_DEVICE_SN] = device_sn

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("Parsed main data: %s", parsed_data)

    except Exception as exc:
        _LOGGER.exception(f"Parse error: {exc}")
        return None

    if parsed_data:
        data_type = "Cells" if is_cell_data else "Main"
        _LOGGER.info(f"Parse OK ({data_type})")
        return parsed_data
    else:
        _LOGGER.warning(f"No data parsed from: {resp_hex[:60] if resp_hex else 'N/A'}...")
        return None

