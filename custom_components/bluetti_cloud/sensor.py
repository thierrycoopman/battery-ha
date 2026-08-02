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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BluettiCloudCoordinator, BluettiConfigEntry
from .entity import BluettiCloudEntity
from .subdevice import build_sub_device_entities

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

# V2 telemetry sensors, populated from the blocks the device pushes.
# Created only for devices on the V2 protocol.
V2_SENSOR_DESCRIPTIONS: list[BluettiSensorDescription] = [
    BluettiSensorDescription(
        key="ambient_temp", data_key="ambient_temp", name="Ambient Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    BluettiSensorDescription(
        key="inverter_temp", data_key="inverter_temp", name="Inverter Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    BluettiSensorDescription(
        key="pv_dcdc_temp", data_key="pv_dcdc_temp", name="PV Converter Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    BluettiSensorDescription(
        key="grid_frequency", data_key="grid_frequency", name="Grid Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
    ),
    BluettiSensorDescription(
        key="grid_import_energy", data_key="grid_import_energy",
        name="Grid Import Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    BluettiSensorDescription(
        key="grid_export_energy", data_key="grid_export_energy",
        name="Grid Export Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    BluettiSensorDescription(
        key="pv_total_energy", data_key="pv_total_energy", name="PV Total Energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    BluettiSensorDescription(
        key="ac_load_power", data_key="ac_load_power", name="AC Load Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    BluettiSensorDescription(
        key="dc_load_power", data_key="dc_load_power", name="DC Load Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    BluettiSensorDescription(
        key="inverter_frequency", data_key="inverter_frequency",
        name="Inverter Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
    ),
    BluettiSensorDescription(
        key="cell_voltage_min", data_key="cell_voltage_min", name="Cell Voltage Min",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
    ),
    BluettiSensorDescription(
        key="cell_voltage_max", data_key="cell_voltage_max", name="Cell Voltage Max",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
    ),
    BluettiSensorDescription(
        key="cell_voltage_delta", data_key="cell_voltage_delta",
        name="Cell Voltage Delta",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:scale-balance",
    ),
]

# Battery aggregate sensors (from FC=16 registers 92-93 and reg 43)
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
]


def _build_pack_descriptions(pack_id: int) -> list[BluettiSensorDescription]:
    """Build sensor descriptions for a specific battery pack.

    AC300 provides per-pack voltage (reg 98) and SOC (reg 99) via FC=16
    register cycling, plus charging status from reg 97.
    """
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
            key=f"{prefix}_soc",
            data_key=f"{prefix}_soc",
            name=f"{label} SOC",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            icon="mdi:battery",
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
    entry: BluettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud sensor entities."""
    coordinator = entry.runtime_data
    device_sns = entry.data.get("devices", [])

    entities: list[BluettiCloudSensor] = []

    for sn in device_sns:
        # Static sensors (always present)
        for description in SENSOR_DESCRIPTIONS:
            entities.append(BluettiCloudSensor(coordinator, sn, description))

        # Pack summary sensors. MQTT devices get voltage + current from
        # PackMainInfo. REST-only devices (e.g. AP300) report only aggregate
        # voltage over REST (no aggregate current), so skip the current sensor
        # rather than create a permanently-unavailable entity.
        profile = coordinator.profile_for(sn)
        if profile.iot_payload_ver >= 1.1:
            for description in V2_SENSOR_DESCRIPTIONS:
                entities.append(BluettiCloudSensor(coordinator, sn, description))

        rest_only = profile.data_path == "rest_only"
        for description in PACK_SUMMARY_DESCRIPTIONS:
            if rest_only and description.data_key != "pack_total_voltage":
                continue
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

    # Per-battery SOC sensors for discovered battery sub-devices (nodes).
    created_nodes: dict[str, set[int]] = {sn: set() for sn in device_sns}

    def _on_nodes(sn: str, nodes: list[dict]) -> None:
        if sn not in created_nodes:
            return
        new_entities: list = []
        for node in nodes:
            if not (node.get("is_battery") or node.get("has_battery")):
                continue
            addr = node["slave_addr"]
            if addr in created_nodes[sn]:
                continue
            created_nodes[sn].add(addr)
            _LOGGER.info(
                "Creating entities for %s expansion at node %d (%s)",
                sn, addr, node.get("model_name"),
            )
            new_entities.extend(
                e for e in build_sub_device_entities(coordinator, sn, node)
                if isinstance(e, SensorEntity)
            )
        if new_entities:
            async_add_entities(new_entities)

    for sn in device_sns:
        _on_nodes(sn, coordinator.get_nodes(sn))
    coordinator.register_node_callback(_on_nodes)


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
