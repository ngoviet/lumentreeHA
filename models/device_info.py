"""Device information models for Lumentree integration."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class LumentreeDeviceInfo:
    """Device information data class."""

    device_id: str
    device_sn: str
    device_name: str
    device_type: Optional[str] = None
    controller_version: Optional[str] = None
    lcd_version: Optional[str] = None
    remark_name: Optional[str] = None

