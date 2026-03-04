"""Sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

import logging
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
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
from .entity import BluettiCloudEntity

_LOGGER = logging.getLogger(__name__)


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

# PackMainInfo summary sensors (from active MQTT polling, reg 6000)
PACK_SUMMARY_DESCRIPTIONS: list[BluettiSensorDescription] = [
    BluettiSensorDescription(
        key="pack_total_voltage",
        data_key="pack_total_voltage",
        name="Battery Total Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:flash",
    ),
    BluettiSensorDescription(
        key="pack_total_current",
        data_key="pack_total_current",
        name="Battery Total Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-ac",
    ),
    BluettiSensorDescription(
        key="pack_total_soc",
        data_key="pack_total_soc",
        name="Battery Total SOC",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery",
    ),
    BluettiSensorDescription(
        key="pack_total_soh",
        data_key="pack_total_soh",
        name="Battery Health",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:battery-heart-variant",
    ),
    BluettiSensorDescription(
        key="pack_average_temp",
        data_key="pack_average_temp",
        name="Battery Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer",
    ),
    BluettiSensorDescription(
        key="charge_full_time",
        data_key="charge_full_time",
        name="Time to Full Charge",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:battery-clock",
    ),
    BluettiSensorDescription(
        key="discharge_empty_time",
        data_key="discharge_empty_time",
        name="Time to Empty",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:battery-clock-outline",
    ),
]


def _build_pack_descriptions(pack_id: int) -> list[BluettiSensorDescription]:
    """Build sensor descriptions for a specific battery pack."""
    prefix = f"pack_{pack_id}"
    label = f"Pack {pack_id}"
    return [
        BluettiSensorDescription(
            key=f"{prefix}_voltage",
            data_key=f"{prefix}_voltage",
            name=f"{label} Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            icon="mdi:flash",
        ),
        BluettiSensorDescription(
            key=f"{prefix}_current",
            data_key=f"{prefix}_current",
            name=f"{label} Current",
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            icon="mdi:current-ac",
        ),
        BluettiSensorDescription(
            key=f"{prefix}_soc",
            data_key=f"{prefix}_soc",
            name=f"{label} SOC",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:battery",
        ),
        BluettiSensorDescription(
            key=f"{prefix}_soh",
            data_key=f"{prefix}_soh",
            name=f"{label} Health",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:battery-heart-variant",
        ),
        BluettiSensorDescription(
            key=f"{prefix}_temp",
            data_key=f"{prefix}_temp",
            name=f"{label} Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
        ),
        BluettiSensorDescription(
            key=f"{prefix}_charging_status",
            data_key=f"{prefix}_charging_status",
            name=f"{label} Charging Status",
            icon="mdi:battery-sync",
        ),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud sensor entities."""
    coordinator: BluettiCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    device_sns = entry.data.get("devices", [])

    entities: list[BluettiCloudSensor] = []

    for sn in device_sns:
        # Static sensors (always present)
        for description in SENSOR_DESCRIPTIONS:
            entities.append(BluettiCloudSensor(coordinator, sn, description))

        # Pack summary sensors (from PackMainInfo)
        for description in PACK_SUMMARY_DESCRIPTIONS:
            entities.append(BluettiCloudSensor(coordinator, sn, description))

        # Per-pack sensors for already-discovered packs
        pack_count = coordinator.get_pack_count(sn)
        for pack_id in range(1, pack_count + 1):
            for description in _build_pack_descriptions(pack_id):
                entities.append(BluettiCloudSensor(coordinator, sn, description))

    async_add_entities(entities)

    # Track which packs we've already created sensors for
    created_packs: dict[str, set[int]] = {sn: set() for sn in device_sns}
    # Pre-populate with already-created packs
    for sn in device_sns:
        for pack_id in range(1, coordinator.get_pack_count(sn) + 1):
            created_packs[sn].add(pack_id)

    def _on_new_packs(sn: str, pack_count: int) -> None:
        """Create sensors for newly discovered battery packs."""
        if sn not in created_packs:
            return

        new_entities: list[BluettiCloudSensor] = []
        for pack_id in range(1, pack_count + 1):
            if pack_id in created_packs[sn]:
                continue
            created_packs[sn].add(pack_id)
            _LOGGER.info("Creating sensors for %s battery pack %d", sn, pack_id)
            for description in _build_pack_descriptions(pack_id):
                new_entities.append(
                    BluettiCloudSensor(coordinator, sn, description)
                )

        if new_entities:
            async_add_entities(new_entities)

    coordinator.register_new_pack_callback(_on_new_packs)


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
