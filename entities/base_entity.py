"""Base entity class for Lumentree integration."""

from typing import Optional
import logging

from homeassistant.helpers.entity import DeviceInfo, Entity

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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

