"""Binary sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud binary sensor entities."""
    coordinator: BluettiCloudCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BluettiCloudBinarySensor] = []
    for sn in entry.data.get("devices", []):
        for description in BINARY_SENSOR_DESCRIPTIONS:
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
