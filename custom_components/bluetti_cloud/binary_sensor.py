"""Binary sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BluettiCloudCoordinator, BluettiConfigEntry
from .entity import BluettiCloudEntity


@dataclass(frozen=True, kw_only=True)
class BluettiBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Bluetti binary sensor."""

    data_key: str
    on_value: str | bool = True


BINARY_SENSOR_DESCRIPTIONS: list[BluettiBinarySensorDescription] = [
    BluettiBinarySensorDescription(
        key="online",
        data_key="online",
        name="Cloud Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BluettiBinarySensorDescription(
        key="iot_session",
        data_key="iot_session",
        name="IoT Session",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        on_value="Online",
        icon="mdi:cloud-check",
    ),
]

# Read-only output-state sensors for REST-only devices (e.g. AP300 / APEX 300),
# which expose AC/DC/PV/grid switch states over REST but cannot be controlled.
# MQTT-capable devices (AC300) get real controllable switches instead.
OUTPUT_STATE_DESCRIPTIONS: list[BluettiBinarySensorDescription] = [
    BluettiBinarySensorDescription(
        key="ac_output_state",
        data_key="ac_switch",
        name="AC Output",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:power-plug",
    ),
    BluettiBinarySensorDescription(
        key="dc_output_state",
        data_key="dc_switch",
        name="DC Output",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:current-dc",
    ),
    BluettiBinarySensorDescription(
        key="pv_input_state",
        data_key="pv_switch",
        name="Solar Input",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:solar-power",
    ),
    BluettiBinarySensorDescription(
        key="grid_input_state",
        data_key="grid_switch",
        name="Grid Input",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:transmission-tower",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BluettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud binary sensor entities."""
    coordinator = entry.runtime_data

    entities: list[BluettiCloudBinarySensor] = []
    for sn in entry.data.get("devices", []):
        for description in BINARY_SENSOR_DESCRIPTIONS:
            entities.append(
                BluettiCloudBinarySensor(coordinator, sn, description)
            )

        # Devices we can't control — surface their AC/DC/PV/grid output states
        # as read-only binary sensors instead of switches. (This covers both
        # REST-only devices and MQTT devices whose control isn't implemented.)
        if not coordinator.profile_for(sn).controllable:
            for description in OUTPUT_STATE_DESCRIPTIONS:
                entities.append(
                    BluettiCloudBinarySensor(coordinator, sn, description)
                )

    async_add_entities(entities)


class BluettiCloudBinarySensor(BluettiCloudEntity, BinarySensorEntity):
    """Bluetti Cloud binary sensor entity."""

    entity_description: BluettiBinarySensorDescription

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        description: BluettiBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, device_sn, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.device_data.get(self.entity_description.data_key)
        if value is None:
            return None
        expected = self.entity_description.on_value
        if isinstance(expected, bool):
            return bool(value)
        return value == expected
