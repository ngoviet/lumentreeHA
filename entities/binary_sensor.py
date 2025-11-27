"""Binary sensor entities for Lumentree integration."""

import logging
from typing import Any, Dict, Optional, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from ..const import (
    DOMAIN,
    CONF_DEVICE_SN,
    CONF_DEVICE_NAME,
    SIGNAL_UPDATE_FORMAT,
    KEY_ONLINE_STATUS,
    KEY_IS_UPS_MODE,
)

_LOGGER = logging.getLogger(__name__)

BINARY_SENSOR_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key=KEY_ONLINE_STATUS,
        name="Online Status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=True,
    ),
    BinarySensorEntityDescription(
        key=KEY_IS_UPS_MODE,
        name="UPS Mode",
        icon="mdi:power-plug-outline",
        device_class=None,
        entity_registry_enabled_default=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensor platform."""
    _LOGGER.debug(f"Setting up binary sensor platform for {entry.title}")

    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        device_sn = entry.data[CONF_DEVICE_SN]
        device_name = entry.data[CONF_DEVICE_NAME]
        device_api_info = entry_data.get("device_api_info", {})
    except KeyError as exc:
        _LOGGER.error(f"Missing key {exc} for binary sensors")
        return

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_sn)},
        name=device_name,
        manufacturer="YS Tech (YiShen)",
        model=device_api_info.get("deviceType"),
        sw_version=device_api_info.get("controllerVersion"),
        hw_version=device_api_info.get("liquidCrystalVersion"),
    )
    _LOGGER.debug(f"Creating DeviceInfo for BinarySensors {device_sn}: {device_info}")

    entities = [
        LumentreeBinarySensor(hass, entry, device_info, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    ]

    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"Added {len(entities)} binary sensors for {device_sn}")


class LumentreeBinarySensor(BinarySensorEntity):
    """Binary sensor entity."""

    __slots__ = (
        "hass",
        "entity_description",
        "_device_sn",
        "_attr_unique_id",
        "_attr_object_id",
        "entity_id",
        "_attr_device_info",
        "_attr_is_on",
        "_remove_dispatcher",
    )

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        self.hass = hass
        self.entity_description = description
        self._device_sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("binary_sensor.{}", self._attr_object_id, hass=hass)
        self._attr_device_info = device_info
        self._attr_is_on = None
        self._remove_dispatcher: Optional[Callable] = None

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Init binary sensor: uid=%s, eid=%s, name=%s",
                self.unique_id,
                self.entity_id,
                self.name,
            )

    @callback
    def _handle_update(self, data: Dict[str, Any]) -> None:
        """Handle updates from the dispatcher."""
        if self.entity_description.key in data:
            new_state = data[self.entity_description.key]
            # Handle both True and False
            if isinstance(new_state, bool):
                if self._attr_is_on != new_state:
                    _LOGGER.info(
                        f"Binary sensor {self.entity_id} state changing to: {new_state}"
                    )
                    self._attr_is_on = new_state
                    self.async_write_ha_state()
            else:
                _LOGGER.warning(
                    f"Received non-boolean value for {self.unique_id}: {new_state}"
                )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection."""
        signal = SIGNAL_UPDATE_FORMAT.format(device_sn=self._device_sn)
        self._remove_dispatcher = async_dispatcher_connect(self.hass, signal, self._handle_update)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Binary sensor %s registered", self.unique_id)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dispatcher connection."""
        if self._remove_dispatcher:
            self._remove_dispatcher()
            self._remove_dispatcher = None
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Binary sensor %s unregistered", self.unique_id)

