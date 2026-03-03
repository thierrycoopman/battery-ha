"""Sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
from .entity import BluettiCloudEntity


@dataclass(frozen=True, kw_only=True)
class BluettiSensorDescription(SensorEntityDescription):
    """Describes a Bluetti sensor."""

    data_key: str


SENSOR_DESCRIPTIONS: list[BluettiSensorDescription] = [
    BluettiSensorDescription(
        key="battery_soc",
        data_key="battery_soc",
        translation_key="battery_soc",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery",
    ),
    BluettiSensorDescription(
        key="total_battery_percent",
        data_key="total_battery_percent",
        translation_key="total_battery_percent",
        name="Total Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery",
    ),
    BluettiSensorDescription(
        key="power_pv_in",
        data_key="power_pv_in",
        translation_key="power_pv_in",
        name="PV Input",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
    ),
    BluettiSensorDescription(
        key="power_grid_in",
        data_key="power_grid_in",
        translation_key="power_grid_in",
        name="Grid Input",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:transmission-tower",
    ),
    BluettiSensorDescription(
        key="power_ac_out",
        data_key="power_ac_out",
        translation_key="power_ac_out",
        name="AC Output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:power-plug",
    ),
    BluettiSensorDescription(
        key="power_dc_out",
        data_key="power_dc_out",
        translation_key="power_dc_out",
        name="DC Output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:current-dc",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud sensor entities."""
    coordinator: BluettiCloudCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BluettiCloudSensor] = []
    for sn in entry.data.get("devices", []):
        for description in SENSOR_DESCRIPTIONS:
            entities.append(BluettiCloudSensor(coordinator, sn, description))

    async_add_entities(entities)


class BluettiCloudSensor(BluettiCloudEntity, SensorEntity):
    """Bluetti Cloud sensor entity."""

    entity_description: BluettiSensorDescription

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        description: BluettiSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_sn, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | None:
        return self.device_data.get(self.entity_description.data_key)
