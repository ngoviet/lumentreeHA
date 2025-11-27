"""Modbus parser for Lumentree MQTT payload.

This module is maintained for backward compatibility.
All parsing functions have been moved to realtime_parser.py.
"""

# Backward compatibility: Re-export all functions from realtime_parser
from .realtime_parser import (
    calculate_crc16_modbus,
    verify_crc,
    generate_modbus_read_command,
    parse_mqtt_payload,
)

__all__ = [
    "calculate_crc16_modbus",
    "verify_crc",
    "generate_modbus_read_command",
    "parse_mqtt_payload",
]
