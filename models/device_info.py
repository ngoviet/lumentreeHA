"""Device information models for Lumentree integration.

DEPRECATED: This dataclass is unused. Use common.build_device_info() instead.
Kept for backward compatibility with external code that may import it.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class LumentreeDeviceInfo:
    """Device information data class (deprecated, use common.build_device_info)."""

    device_id: str
    device_sn: str
    device_name: str
    device_type: str | None = None
    controller_version: str | None = None
    lcd_version: str | None = None
    remark_name: str | None = None

