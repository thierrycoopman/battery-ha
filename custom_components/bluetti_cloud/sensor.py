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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
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
    # Battery
    BluettiSensorDescription(
        key="battery_soc",
        data_key="battery_soc",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    # Power sensors
    BluettiSensorDescription(
        key="power_pv_in",
        data_key="power_pv_in",
        name="Solar Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:solar-power",
    ),
    BluettiSensorDescription(
        key="power_grid_in",
        data_key="power_grid_in",
        name="Grid Input Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:transmission-tower",
    ),
    BluettiSensorDescription(
        key="power_ac_out",
        data_key="power_ac_out",
        name="AC Output Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:power-plug",
    ),
    BluettiSensorDescription(
        key="power_dc_out",
        data_key="power_dc_out",
        name="DC Output Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:current-dc",
    ),
    BluettiSensorDescription(
        key="power_feed_back",
        data_key="power_feed_back",
        name="Grid Feed-in Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:transmission-tower-export",
    ),
    # MQTT-sourced sensors (real-time from device telemetry)
    BluettiSensorDescription(
        key="pack_voltage",
        data_key="pack_voltage",
        name="Pack Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:flash",
    ),
    BluettiSensorDescription(
        key="pack_current",
        data_key="pack_current",
        name="Pack Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-ac",
    ),
    BluettiSensorDescription(
        key="charge_time_remaining",
        data_key="charge_time_remaining",
        name="Charge Time Remaining",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:battery-charging",
    ),
    BluettiSensorDescription(
        key="discharge_time_remaining",
        data_key="discharge_time_remaining",
        name="Discharge Time Remaining",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:battery-outline",
    ),
    BluettiSensorDescription(
        key="charging_status",
        data_key="charging_status",
        name="Charging Status",
        icon="mdi:battery-sync",
    ),
    # Energy sensors (for HA Energy Dashboard)
    BluettiSensorDescription(
        key="energy_day",
        data_key="energy_day",
        name="Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power-variant",
    ),
    BluettiSensorDescription(
        key="energy_month",
        data_key="energy_month",
        name="Energy This Month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:calendar-month",
    ),
    BluettiSensorDescription(
        key="energy_year",
        data_key="energy_year",
        name="Energy This Year",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:calendar",
    ),
    BluettiSensorDescription(
        key="energy_total",
        data_key="energy_total",
        name="Lifetime Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:lightning-bolt",
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
    def native_value(self) -> int | float | str | None:
        return self.device_data.get(self.entity_description.data_key)
