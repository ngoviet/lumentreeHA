"""Sensor entities for Lumentree integration."""

from typing import Any, Dict, Optional, Callable
import logging
import re

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfPower,
    UnitOfEnergy,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfElectricCurrent,
    UnitOfApparentPower,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from ..const import (
    DOMAIN,
    CONF_DEVICE_SN,
    CONF_DEVICE_NAME,
    SIGNAL_UPDATE_FORMAT,
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
    KEY_BATTERY_STATUS,
    KEY_GRID_STATUS,
    KEY_AC_IN_VOLTAGE,
    KEY_AC_IN_FREQ,
    KEY_AC_IN_POWER,
    KEY_BATTERY_TYPE,
    KEY_MASTER_SLAVE_STATUS,
    KEY_MQTT_DEVICE_SN,
    KEY_BATTERY_CELL_INFO,
    KEY_DAILY_PV_KWH,
    KEY_DAILY_CHARGE_KWH,
    KEY_DAILY_DISCHARGE_KWH,
    KEY_DAILY_GRID_IN_KWH,
    KEY_DAILY_LOAD_KWH,
    KEY_DAILY_ESSENTIAL_KWH,
    KEY_DAILY_TOTAL_LOAD_KWH,
    KEY_TOTAL_LOAD_POWER,
    KEY_LAST_RAW_MQTT,
    KEY_MONTHLY_PV_KWH,
    KEY_MONTHLY_GRID_IN_KWH,
    KEY_MONTHLY_LOAD_KWH,
    KEY_MONTHLY_ESSENTIAL_KWH,
    KEY_MONTHLY_TOTAL_LOAD_KWH,
    KEY_MONTHLY_CHARGE_KWH,
    KEY_MONTHLY_DISCHARGE_KWH,
    KEY_YEARLY_PV_KWH,
    KEY_YEARLY_GRID_IN_KWH,
    KEY_YEARLY_LOAD_KWH,
    KEY_YEARLY_ESSENTIAL_KWH,
    KEY_YEARLY_TOTAL_LOAD_KWH,
    KEY_YEARLY_CHARGE_KWH,
    KEY_YEARLY_DISCHARGE_KWH,
    KEY_TOTAL_PV_KWH,
    KEY_TOTAL_GRID_IN_KWH,
    KEY_TOTAL_LOAD_KWH,
    KEY_TOTAL_ESSENTIAL_KWH,
    KEY_TOTAL_TOTAL_LOAD_KWH,
    KEY_TOTAL_CHARGE_KWH,
    KEY_TOTAL_DISCHARGE_KWH,
)
from ..coordinators.daily_coordinator import DailyStatsCoordinator
from ..coordinators.monthly_coordinator import MonthlyStatsCoordinator
from ..coordinators.yearly_coordinator import YearlyStatsCoordinator
from ..coordinators.total_coordinator import TotalStatsCoordinator

_LOGGER = logging.getLogger(__name__)

# Sensor Descriptions (MQTT Realtime)
REALTIME_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=KEY_PV_POWER,
        name="PV Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_POWER,
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key=KEY_GRID_POWER,
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower",
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key=KEY_LOAD_POWER,
        name="Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:power-plug",
    ),
    SensorEntityDescription(
        key=KEY_AC_OUT_POWER,
        name="AC Output Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_LOAD_POWER,
        name="Total Load Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:power-plug-outline",
    ),
    SensorEntityDescription(
        key=KEY_AC_IN_POWER,
        name="AC Input Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key=KEY_PV1_POWER,
        name="PV1 Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_PV2_POWER,
        name="PV2 Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_AC_OUT_VA,
        name="AC Output Apparent Power",
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_VOLTAGE,
        name="Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-outline",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key=KEY_AC_OUT_VOLTAGE,
        name="AC Output Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_GRID_VOLTAGE,
        name="Grid Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_AC_IN_VOLTAGE,
        name="AC Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_PV1_VOLTAGE,
        name="PV1 Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_PV2_VOLTAGE,
        name="PV2 Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_CURRENT,
        name="Battery Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:current-dc",
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key=KEY_AC_OUT_FREQ,
        name="AC Output Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key=KEY_AC_IN_FREQ,
        name="AC Input Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=True,
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_SOC,
        name="Battery SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_STATUS,
        name="Battery Status",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:battery-sync-outline",
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_TYPE,
        name="Battery Type",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:battery-unknown",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key=KEY_GRID_STATUS,
        name="Grid Status",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:transmission-tower-export",
    ),
    SensorEntityDescription(
        key=KEY_DEVICE_TEMP,
        name="Device Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_MASTER_SLAVE_STATUS,
        name="Master/Slave Status",
        icon="mdi:account-multiple",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key=KEY_MQTT_DEVICE_SN,
        name="Device SN (MQTT)",
        icon="mdi:barcode-scan",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key=KEY_BATTERY_CELL_INFO,
        name="Battery Cell Info",
        icon="mdi:battery-heart-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key=KEY_LAST_RAW_MQTT,
        name="Last Raw MQTT Hex",
        icon="mdi:text-hexadecimal",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

# Sensor Descriptions (HTTP Daily Stats)
STATS_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=KEY_DAILY_PV_KWH,
        name="PV Generation Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_CHARGE_KWH,
        name="Battery Charge Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-plus-variant",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_DISCHARGE_KWH,
        name="Battery Discharge Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-minus-variant",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_GRID_IN_KWH,
        name="Grid Input Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:transmission-tower-import",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_LOAD_KWH,
        name="Load Consumption Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_ESSENTIAL_KWH,
        name="Essential Load Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:power-plug",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_DAILY_TOTAL_LOAD_KWH,
        name="Total Load Today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt-circle",
        suggested_display_precision=1,
    ),
)

MONTH_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=KEY_MONTHLY_PV_KWH,
        name="PV Generation This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_CHARGE_KWH,
        name="Battery Charge This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-plus-variant",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_DISCHARGE_KWH,
        name="Battery Discharge This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-minus-variant",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_GRID_IN_KWH,
        name="Grid Input This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_LOAD_KWH,
        name="Load Consumption This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:home-lightning-bolt",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_ESSENTIAL_KWH,
        name="Essential Load This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:power-plug",
    ),
    SensorEntityDescription(
        key=KEY_MONTHLY_TOTAL_LOAD_KWH,
        name="Total Load This Month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
    ),
)

YEAR_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=KEY_YEARLY_PV_KWH,
        name="PV Generation This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_CHARGE_KWH,
        name="Battery Charge This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-plus-variant",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_DISCHARGE_KWH,
        name="Battery Discharge This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-minus-variant",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_GRID_IN_KWH,
        name="Grid Input This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_LOAD_KWH,
        name="Load Consumption This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:home-lightning-bolt",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_ESSENTIAL_KWH,
        name="Essential Load This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:power-plug",
    ),
    SensorEntityDescription(
        key=KEY_YEARLY_TOTAL_LOAD_KWH,
        name="Total Load This Year",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
    ),
)

# Sensor Descriptions (HTTP Total Stats - Lifetime)
TOTAL_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=KEY_TOTAL_PV_KWH,
        name="PV Generation Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:solar-power",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_CHARGE_KWH,
        name="Battery Charge Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-plus-variant",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_DISCHARGE_KWH,
        name="Battery Discharge Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-minus-variant",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_GRID_IN_KWH,
        name="Grid Input Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:transmission-tower-import",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_LOAD_KWH,
        name="Load Consumption Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:home-lightning-bolt",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_ESSENTIAL_KWH,
        name="Essential Load Total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:power-plug",
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key=KEY_TOTAL_TOTAL_LOAD_KWH,
        name="Total Load (Total)",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt-circle",
        suggested_display_precision=1,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor platform."""
    _LOGGER.debug(f"Setting up sensor platform for {entry.title}")

    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        daily_coord: Optional[DailyStatsCoordinator] = entry_data.get("daily_coordinator")
        monthly_coord: Optional[MonthlyStatsCoordinator] = entry_data.get("monthly_coordinator")
        yearly_coord: Optional[YearlyStatsCoordinator] = entry_data.get("yearly_coordinator")
        total_coord: Optional[TotalStatsCoordinator] = entry_data.get("total_coordinator")
        device_sn = entry.data[CONF_DEVICE_SN]
        device_name = entry.data[CONF_DEVICE_NAME]
        device_api_info = entry_data.get("device_api_info", {})
    except KeyError as exc:
        _LOGGER.error(f"Missing key {exc} in entry data")
        return

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_sn)},
        name=device_name,
        manufacturer="YS Tech (YiShen)",
        model=device_api_info.get("deviceType"),
        sw_version=device_api_info.get("controllerVersion"),
        hw_version=device_api_info.get("liquidCrystalVersion"),
    )
    _LOGGER.debug(f"Creating DeviceInfo for sensors {device_sn}: {device_info}")

    entities_to_add: list[SensorEntity] = []

    for description in REALTIME_SENSOR_DESCRIPTIONS:
        if description.key == KEY_BATTERY_CELL_INFO:
            entities_to_add.append(
                LumentreeBatteryCellSensor(hass, entry, device_info, description, {})
            )
        elif description.key == KEY_TOTAL_LOAD_POWER:
            entities_to_add.append(
                LumentreeTotalLoadPowerSensor(hass, entry, device_info, description, {})
            )
        else:
            entities_to_add.append(
                LumentreeMqttSensor(hass, entry, device_info, description, {})
            )

    _LOGGER.info(f"Adding {len(REALTIME_SENSOR_DESCRIPTIONS)} real-time sensors for {device_sn}")

    if daily_coord:
        for description in STATS_SENSOR_DESCRIPTIONS:
            entities_to_add.append(
                LumentreeDailyStatsSensor(daily_coord, device_info, description)
            )
        _LOGGER.info(f"Adding {len(STATS_SENSOR_DESCRIPTIONS)} daily stats sensors for {device_sn}")
    else:
        _LOGGER.warning(f"Daily coordinator not available for {device_sn}")

    if monthly_coord:
        for description in MONTH_SENSOR_DESCRIPTIONS:
            entities_to_add.append(
                LumentreeMonthlyStatsSensor(monthly_coord, device_info, description)
            )
        _LOGGER.info(f"Adding {len(MONTH_SENSOR_DESCRIPTIONS)} monthly stats sensors for {device_sn}")
    else:
        _LOGGER.warning(f"Monthly coordinator not available for {device_sn}")

    if yearly_coord:
        for description in YEAR_SENSOR_DESCRIPTIONS:
            entities_to_add.append(
                LumentreeYearlyStatsSensor(yearly_coord, device_info, description)
            )
        _LOGGER.info(f"Adding {len(YEAR_SENSOR_DESCRIPTIONS)} yearly stats sensors for {device_sn}")
    else:
        _LOGGER.warning(f"Yearly coordinator not available for {device_sn}")

    # Add total sensors
    _LOGGER.info(f"Total coordinator available: {total_coord is not None}")
    if total_coord:
        for description in TOTAL_SENSOR_DESCRIPTIONS:
            entities_to_add.append(
                LumentreeTotalStatsSensor(total_coord, device_info, description)
            )
        _LOGGER.info(f"Adding {len(TOTAL_SENSOR_DESCRIPTIONS)} total stats sensors for {device_sn}")
    else:
        _LOGGER.warning(f"Total coordinator not available for {device_sn}")

    if entities_to_add:
        async_add_entities(entities_to_add)
    else:
        _LOGGER.warning(f"No sensors added for {device_sn}")


class LumentreeMqttSensor(SensorEntity):
    """MQTT sensor entity."""

    __slots__ = (
        "hass",
        "entity_description",
        "_device_sn",
        "_attr_unique_id",
        "_attr_object_id",
        "entity_id",
        "_attr_device_info",
        "_remove_dispatcher",
        "_attr_native_value",
    )

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        initial_data: Dict[str, Any],
    ) -> None:
        """Initialize MQTT sensor."""
        self.hass = hass
        self.entity_description = description
        self._device_sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", self._attr_object_id, hass=hass)
        self._attr_device_info = device_info
        self._remove_dispatcher: Optional[Callable[[], None]] = None
        self._attr_native_value = self._process_value(initial_data.get(description.key))

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Init MQTT sensor: uid=%s, name=%s, initial_state=%s",
                self.unique_id,
                self.name,
                self._attr_native_value,
            )

    def _process_value(self, value: Any) -> Any:
        """Process value before setting state."""
        processed_value: Any = None
        if value is not None:
            desc = self.entity_description
            if (
                desc.state_class
                in [
                    SensorStateClass.MEASUREMENT,
                    SensorStateClass.TOTAL,
                    SensorStateClass.TOTAL_INCREASING,
                ]
                and desc.native_unit_of_measurement != PERCENTAGE
            ):
                try:
                    processed_value = float(value)
                except (ValueError, TypeError):
                    pass
            elif desc.native_unit_of_measurement == PERCENTAGE or desc.key == KEY_MASTER_SLAVE_STATUS:
                try:
                    processed_value = int(value)
                except (ValueError, TypeError):
                    pass
            else:
                processed_value = str(value)
                if desc.key == KEY_LAST_RAW_MQTT and len(processed_value) > 255:
                    processed_value = processed_value[:252] + "..."
        return processed_value

    @callback
    def _handle_update(self, data: Dict[str, Any]) -> None:
        """Handle update from dispatcher."""
        key = self.entity_description.key
        if key == KEY_BATTERY_CELL_INFO:
            return
        if key in data:
            new_value = self._process_value(data[key])
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                self.async_write_ha_state()
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug("Update MQTT sensor %s: %s", self.entity_id, new_value)

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection."""
        signal = SIGNAL_UPDATE_FORMAT.format(device_sn=self._device_sn)
        self._remove_dispatcher = async_dispatcher_connect(self.hass, signal, self._handle_update)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("MQTT sensor %s registered", self.unique_id)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dispatcher connection."""
        if self._remove_dispatcher:
            self._remove_dispatcher()
            self._remove_dispatcher = None
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("MQTT sensor %s unregistered", self.unique_id)


class LumentreeBatteryCellSensor(SensorEntity):
    """Battery cell sensor entity."""

    __slots__ = (
        "hass",
        "entity_description",
        "_device_sn",
        "_attr_unique_id",
        "_attr_object_id",
        "entity_id",
        "_attr_device_info",
        "_attr_extra_state_attributes",
        "_remove_dispatcher",
        "_attr_native_value",
    )

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        initial_data: Dict[str, Any],
    ) -> None:
        """Initialize cell sensor."""
        self.hass = hass
        self.entity_description = description
        self._device_sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", self._attr_object_id, hass=hass)
        self._attr_device_info = device_info
        self._attr_extra_state_attributes: Dict[str, Any] = {}
        self._remove_dispatcher: Optional[Callable[[], None]] = None

        initial_cell_info = initial_data.get(KEY_BATTERY_CELL_INFO)
        if isinstance(initial_cell_info, dict):
            self._attr_native_value = initial_cell_info.get("number_of_cells")
            self._attr_extra_state_attributes = initial_cell_info
        else:
            self._attr_native_value = None

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Init Cell sensor: uid=%s, name=%s, initial_state=%s",
                self.unique_id,
                self.name,
                self._attr_native_value,
            )

    @callback
    def _handle_update(self, data: Dict[str, Any]) -> None:
        """Handle update from dispatcher."""
        if KEY_BATTERY_CELL_INFO in data:
            cell_info_dict = data[KEY_BATTERY_CELL_INFO]
            if isinstance(cell_info_dict, dict):
                new_state = cell_info_dict.get("number_of_cells")
                new_attrs = cell_info_dict
                if (
                    self._attr_native_value != new_state
                    or self._attr_extra_state_attributes != new_attrs
                ):
                    self._attr_native_value = new_state
                    self._attr_extra_state_attributes = new_attrs
                    self.async_write_ha_state()
                    _LOGGER.info(f"Update Cell sensor {self.entity_id}: State={new_state}")
            else:
                _LOGGER.warning(
                    f"Invalid cell info type {self.unique_id}: {type(cell_info_dict)}"
                )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher connection."""
        signal = SIGNAL_UPDATE_FORMAT.format(device_sn=self._device_sn)
        self._remove_dispatcher = async_dispatcher_connect(self.hass, signal, self._handle_update)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Cell sensor %s registered", self.unique_id)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dispatcher connection."""
        if self._remove_dispatcher:
            self._remove_dispatcher()
            self._remove_dispatcher = None
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Cell sensor %s unregistered", self.unique_id)


class LumentreeDailyStatsSensor(CoordinatorEntity[DailyStatsCoordinator], SensorEntity):
    """Daily statistics sensor entity."""

    __slots__ = (
        "entity_description",
        "_device_sn",
        "_attr_unique_id",
        "_attr_object_id",
        "entity_id",
        "_attr_device_info",
        "_attr_attribution",
        "_attr_native_value",
    )

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DailyStatsCoordinator,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize stats sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_sn = coordinator.device_sn
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", self._attr_object_id, hass=coordinator.hass)
        self._attr_device_info = device_info
        self._attr_attribution = "Data fetched via Lumentree HTTP API"
        self._attr_native_value = None
        self._update_state_from_coordinator()

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Init Stats sensor: uid=%s, eid=%s, name=%s", self.unique_id, self.entity_id, self.name
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update."""
        self._update_state_from_coordinator()
        self.async_write_ha_state()
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Stats sensor %s updated", self.entity_id)

    def _update_state_from_coordinator(self) -> None:
        """Update state from coordinator data."""
        key = self.entity_description.key
        value = self.coordinator.data.get(key) if self.coordinator.data else None
        self._attr_native_value = round(value, 2) if isinstance(value, (int, float)) else None

    @property
    def available(self) -> bool:
        """Return availability."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes with hourly and 5-minute series data."""
        if not self.coordinator.data:
            return {}
        
        key = self.entity_description.key
        attrs: Dict[str, Any] = {}
        
        # Map sensor keys to series data keys
        series_mapping = {
            KEY_DAILY_PV_KWH: {
                "series_5min_w": "pv_series_5min_w",
                "series_5min_kwh": "pv_series_5min_kwh",
                "series_hour_kwh": "pv_series_hour_kwh",
            },
            KEY_DAILY_GRID_IN_KWH: {
                "series_5min_w": "grid_series_5min_w",
                "series_5min_kwh": "grid_series_5min_kwh",
                "series_hour_kwh": "grid_series_hour_kwh",
            },
            KEY_DAILY_LOAD_KWH: {
                "series_5min_w": "load_series_5min_w",
                "series_5min_kwh": "load_series_5min_kwh",
                "series_hour_kwh": "load_series_hour_kwh",
            },
            KEY_DAILY_ESSENTIAL_KWH: {
                "series_5min_w": "essential_series_5min_w",
                "series_5min_kwh": "essential_series_5min_kwh",
                "series_hour_kwh": "essential_series_hour_kwh",
            },
            KEY_DAILY_TOTAL_LOAD_KWH: {
                "series_5min_w": "total_load_series_5min_w",
                "series_5min_kwh": "total_load_series_5min_kwh",
                "series_hour_kwh": "total_load_series_hour_kwh",
            },
            KEY_DAILY_CHARGE_KWH: {
                "series_hour_kwh": "battery_charge_series_hour_kwh",
            },
            KEY_DAILY_DISCHARGE_KWH: {
                "series_hour_kwh": "battery_discharge_series_hour_kwh",
            },
        }
        
        # Get mapping for this sensor key
        if key in series_mapping:
            mapping = series_mapping[key]
            for attr_key, data_key in mapping.items():
                value = self.coordinator.data.get(data_key)
                if value is not None:
                    attrs[attr_key] = value
            
            # For battery sensors, also include 5min_w if available (charge/discharge separated)
            if key in (KEY_DAILY_CHARGE_KWH, KEY_DAILY_DISCHARGE_KWH):
                battery_series = self.coordinator.data.get("battery_series_5min_w")
                if battery_series and isinstance(battery_series, list):
                    # Extract only positive (charge) or negative (discharge) values
                    # Note: API returns positive = discharge, negative = charge, but api_client inverts it
                    # After inversion in api_client: positive = charge, negative = discharge
                    # Charge shows as positive (above 0), Discharge shows as negative (below 0)
                    if key == KEY_DAILY_CHARGE_KWH:
                        # Charge: keep positive values (show above 0 on chart)
                        attrs["series_5min_w"] = [w if w > 0 else 0.0 for w in battery_series]
                    else:  # discharge
                        # Discharge: keep negative values (show below 0 on chart)
                        attrs["series_5min_w"] = [w if w < 0 else 0.0 for w in battery_series]
                    
                    # Convert to kWh
                    if attrs.get("series_5min_w"):
                        attrs["series_5min_kwh"] = [
                            round(w * (5.0 / 60.0) / 1000.0, 6) 
                            for w in attrs["series_5min_w"]
                        ]
        
        # Add source date if available (from coordinator update time or query_date)
        # Try to get from data first, otherwise use current date from coordinator
        if "source_date" in self.coordinator.data:
            attrs["source_date"] = self.coordinator.data["source_date"]
        else:
            # Fallback: use today's date (coordinator fetches today's data)
            from homeassistant.util import dt as dt_util
            timezone = dt_util.get_time_zone(self.coordinator.hass.config.time_zone) or dt_util.get_default_time_zone()
            attrs["source_date"] = dt_util.now(timezone).strftime("%Y-%m-%d")
        
        # Add savings data if available (calculated in daily coordinator)
        if "saved_kwh" in self.coordinator.data:
            attrs["saved_kwh"] = self.coordinator.data["saved_kwh"]
        if "savings_vnd" in self.coordinator.data:
            attrs["savings_vnd"] = self.coordinator.data["savings_vnd"]
        
        return attrs


class LumentreeTotalLoadPowerSensor(SensorEntity):
    """Total load power sensor (calculated)."""

    __slots__ = (
        "hass",
        "entity_description",
        "_device_sn",
        "_attr_unique_id",
        "_attr_object_id",
        "entity_id",
        "_attr_device_info",
        "_remove_dispatcher",
        "_load_power",
        "_ac_output_power",
        "_attr_native_value",
    )

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        description: SensorEntityDescription,
        initial_data: Dict[str, Any],
    ) -> None:
        """Initialize total load power sensor."""
        self.hass = hass
        self.entity_description = description
        self._device_sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", self._attr_object_id, hass=hass)
        self._attr_device_info = device_info
        self._remove_dispatcher: Optional[Callable] = None

        # Store component values
        self._load_power: Optional[float] = None
        self._ac_output_power: Optional[float] = None

        # Calculate initial value
        self._load_power = self._safe_float(initial_data.get(KEY_LOAD_POWER))
        self._ac_output_power = self._safe_float(initial_data.get(KEY_AC_OUT_POWER))
        self._attr_native_value = None
        self._calculate_total_load_power()

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Init Total Load Power sensor: uid=%s, name=%s, initial_state=%s",
                self.unique_id,
                self.name,
                self._attr_native_value,
            )

    def _safe_float(self, value: Any) -> Optional[float]:
        """Convert value to float safely."""
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                pass
        return None

    def _calculate_total_load_power(self) -> None:
        """Calculate total load power."""
        if self._load_power is not None and self._ac_output_power is not None:
            self._attr_native_value = round(self._load_power + self._ac_output_power, 2)
        else:
            self._attr_native_value = None

    @callback
    def _handle_update(self, data: Dict[str, Any]) -> None:
        """Handle update from MQTT dispatcher."""
        updated = False

        # Update load power
        if KEY_LOAD_POWER in data:
            new_load_power = self._safe_float(data[KEY_LOAD_POWER])
            if self._load_power != new_load_power:
                self._load_power = new_load_power
                updated = True

        # Update AC output power
        if KEY_AC_OUT_POWER in data:
            new_ac_output_power = self._safe_float(data[KEY_AC_OUT_POWER])
            if self._ac_output_power != new_ac_output_power:
                self._ac_output_power = new_ac_output_power
                updated = True

        # Recalculate and update state
        if updated:
            old_value = self._attr_native_value
            self._calculate_total_load_power()
            if self._attr_native_value != old_value:
                self.async_write_ha_state()
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Update Total Load Power sensor %s: Load=%sW, AC_Out=%sW, Total=%sW",
                        self.entity_id,
                        self._load_power,
                        self._ac_output_power,
                        self._attr_native_value,
                    )

    async def async_added_to_hass(self) -> None:
        """Register MQTT dispatcher connection."""
        signal = SIGNAL_UPDATE_FORMAT.format(device_sn=self._device_sn)
        self._remove_dispatcher = async_dispatcher_connect(self.hass, signal, self._handle_update)
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Total Load Power sensor %s registered", self.unique_id)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister dispatcher connection."""
        if self._remove_dispatcher:
            self._remove_dispatcher()
            self._remove_dispatcher = None
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Total Load Power sensor %s unregistered", self.unique_id)


class _BaseCoordinatorSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, device_info: DeviceInfo, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._device_sn = getattr(coordinator, "device_sn", "unknown")
        self._attr_unique_id = f"{self._device_sn}_{description.key}"
        object_id = f"device_{self._device_sn}_{slugify(description.key)}"
        self._attr_object_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", self._attr_object_id, hass=coordinator.hass)
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._update_state_from_coordinator()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state_from_coordinator()
        self.async_write_ha_state()

    def _update_state_from_coordinator(self) -> None:
        key = self.entity_description.key
        value = self.coordinator.data.get(key) if self.coordinator.data else None
        self._attr_native_value = round(value, 2) if isinstance(value, (int, float)) else None


class LumentreeMonthlyStatsSensor(_BaseCoordinatorSensor):
    def __init__(self, coordinator: MonthlyStatsCoordinator, device_info: DeviceInfo, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, device_info, description)
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes for charting."""
        if not self.coordinator.data:
            return {}
        
        return {
            "daily_pv": self.coordinator.data.get("daily_pv", []),
            "daily_charge": self.coordinator.data.get("daily_charge", []),
            "daily_discharge": self.coordinator.data.get("daily_discharge", []),
            "daily_grid": self.coordinator.data.get("daily_grid", []),
            "daily_load": self.coordinator.data.get("daily_load", []),
            "daily_essential": self.coordinator.data.get("daily_essential", []),
            "daily_total_load": self.coordinator.data.get("daily_total_load", []),
            "daily_saved_kwh": self.coordinator.data.get("daily_saved_kwh", []),
            "daily_savings_vnd": self.coordinator.data.get("daily_savings_vnd", []),
            "days_in_month": self.coordinator.data.get("days_in_month", 31),
            "year": self.coordinator.data.get("year"),
            "month": self.coordinator.data.get("month"),
        }


class LumentreeYearlyStatsSensor(_BaseCoordinatorSensor):
    def __init__(self, coordinator: YearlyStatsCoordinator, device_info: DeviceInfo, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, device_info, description)
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes for yearly charting."""
        if not self.coordinator.data:
            return {}
        
        return {
            "monthly_pv": self.coordinator.data.get("monthly_pv", []),
            "monthly_grid": self.coordinator.data.get("monthly_grid", []),
            "monthly_load": self.coordinator.data.get("monthly_load", []),
            "monthly_essential": self.coordinator.data.get("monthly_essential", []),
            "monthly_total_load": self.coordinator.data.get("monthly_total_load", []),
            "monthly_charge": self.coordinator.data.get("monthly_charge", []),
            "monthly_discharge": self.coordinator.data.get("monthly_discharge", []),
            "monthly_saved_kwh": self.coordinator.data.get("monthly_saved_kwh", []),
            "monthly_savings_vnd": self.coordinator.data.get("monthly_savings_vnd", []),
            "year": self.coordinator.data.get("year"),
        }


class LumentreeTotalStatsSensor(_BaseCoordinatorSensor):
    def __init__(self, coordinator: TotalStatsCoordinator, device_info: DeviceInfo, description: SensorEntityDescription) -> None:
        super().__init__(coordinator, device_info, description)
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes for total statistics."""
        if not self.coordinator.data:
            return {}
        
        return {
            "years_processed": self.coordinator.data.get("years_processed", 0),
            "earliest_year": self.coordinator.data.get("earliest_year"),
            "latest_year": self.coordinator.data.get("latest_year"),
            "last_updated": self.coordinator.data.get("last_updated"),
        }
