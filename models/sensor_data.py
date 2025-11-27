"""Sensor data models for Lumentree integration."""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class SensorData:
    """Sensor data container."""

    timestamp: float
    data: Dict[str, Any]
    device_sn: str
    is_valid: bool = True
    error: Optional[str] = None

