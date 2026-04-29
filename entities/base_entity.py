"""Base entity class for Lumentree integration.

DEPRECATED: This class is no longer used by any entity. Sensor entities now extend
SensorEntity directly (MQTT sensors) or CoordinatorEntity + SensorEntity (stats sensors).
Kept for backward compatibility with external code that may import it.
"""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity


class LumentreeBaseEntity(Entity):
    """Base class for Lumentree entities."""

    __slots__ = ("_device_sn", "_attr_unique_id", "_attr_device_info")

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device_sn: str, device_info: DeviceInfo) -> None:
        """Initialize base entity.

        Args:
            device_sn: Device serial number
            device_info: Device information
        """
        self._device_sn = device_sn
        self._attr_device_info = device_info
        self._attr_unique_id: Optional[str] = None

    @property
    def device_sn(self) -> str:
        """Return device serial number."""
        return self._device_sn

