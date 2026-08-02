"""Entity definitions for expansions attached to a main unit.

An expansion is anything the main unit reports as a mesh node: a battery
(B300, B300K, B500K, …) or a hub (D1 / DC hub, A1 / AC hub, SolarX). Each one
becomes its own Home Assistant device, so a setup that grows over time stays
navigable and a dashboard can target a single expansion.

What a given expansion exposes depends on what it actually reports:

* every expansion gets a **connectivity** sensor, plus fault flags
* batteries additionally get **state of charge**, and voltage / temperature /
  cell detail when the pack reports them

Nothing here is model-specific. A battery model that isn't in the catalogue
still appears with its raw code (`Battery (4099)`), and a new hub type is
handled the same way as the D1 — the node record drives everything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfTemperature,
)

from .coordinator import BluettiCloudCoordinator
from .entity import BluettiSubDeviceEntity


@dataclass(frozen=True, kw_only=True)
class SubDeviceSensorSpec:
    """A sensor derived from an expansion's node or pack data."""

    key: str
    name: str
    source: str  # field name in the node record
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    unit: str | None = None
    icon: str | None = None
    battery_only: bool = True
    enabled_default: bool = True


SUB_DEVICE_SENSORS: tuple[SubDeviceSensorSpec, ...] = (
    SubDeviceSensorSpec(
        key="soc", name="Battery", source="pack_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT, unit=PERCENTAGE,
    ),
    SubDeviceSensorSpec(
        key="voltage", name="Voltage", source="pack_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
    ),
    SubDeviceSensorSpec(
        key="temperature", name="Temperature", source="pack_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfTemperature.CELSIUS,
    ),
    SubDeviceSensorSpec(
        key="cell_delta", name="Cell Balance", source="cell_voltage_delta",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT, icon="mdi:scale-balance",
    ),
    SubDeviceSensorSpec(
        key="cell_count", name="Cells", source="cell_count",
        icon="mdi:battery-heart-variant", enabled_default=False,
    ),
)


class BluettiSubDeviceSensor(BluettiSubDeviceEntity, SensorEntity):
    """A reading reported by one expansion."""

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        parent_sn: str,
        slave_addr: int,
        spec: SubDeviceSensorSpec,
    ) -> None:
        super().__init__(coordinator, parent_sn, slave_addr, spec.key)
        self._spec = spec
        self._attr_name = spec.name
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon
        self._attr_entity_registry_enabled_default = spec.enabled_default

    @property
    def native_value(self) -> Any:
        return self.node.get(self._spec.source)

    @property
    def available(self) -> bool:
        # A pack that doesn't report a given field (voltage while idle, for
        # example) shouldn't present a stale or invented reading.
        return super().available and self.node.get(self._spec.source) is not None


class BluettiSubDeviceConnectivity(BluettiSubDeviceEntity, BinarySensorEntity):
    """Whether an expansion is currently reported as online."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        parent_sn: str,
        slave_addr: int,
    ) -> None:
        super().__init__(coordinator, parent_sn, slave_addr, "online")
        self._attr_name = "Connection"

    @property
    def is_on(self) -> bool | None:
        return self.node.get("online")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        node = self.node
        attrs: dict[str, Any] = {
            "model": node.get("model_name"),
            "model_code": node.get("model"),
            "type": "battery" if node.get("is_battery") else "expansion",
            "slave_address": self._slave_addr,
        }
        if node.get("pack_serial"):
            attrs["serial"] = node["pack_serial"]
        return attrs


class BluettiSubDeviceFault(BluettiSubDeviceEntity, BinarySensorEntity):
    """Warning or error state reported for an expansion."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        parent_sn: str,
        slave_addr: int,
    ) -> None:
        super().__init__(coordinator, parent_sn, slave_addr, "fault")
        self._attr_name = "Fault"

    @property
    def is_on(self) -> bool | None:
        node = self.node
        if not node:
            return None
        return bool(node.get("warning") or node.get("error"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        node = self.node
        return {
            "warning": node.get("warning"),
            "error": node.get("error"),
            "upgrading": node.get("upgrading"),
        }


def build_sub_device_entities(
    coordinator: BluettiCloudCoordinator, parent_sn: str, node: dict[str, Any]
) -> list[BluettiSubDeviceEntity]:
    """Entities for one expansion, chosen from what it reports."""
    slave = node["slave_addr"]
    entities: list[BluettiSubDeviceEntity] = [
        BluettiSubDeviceConnectivity(coordinator, parent_sn, slave),
        BluettiSubDeviceFault(coordinator, parent_sn, slave),
    ]
    # A battery-model expansion, or any node that reports its own pack (the
    # main unit does this for its internal battery).
    if node.get("is_battery") or node.get("has_battery"):
        entities.extend(
            BluettiSubDeviceSensor(coordinator, parent_sn, slave, spec)
            for spec in SUB_DEVICE_SENSORS
        )
    return entities
