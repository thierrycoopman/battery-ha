"""Binary sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
from .entity import BluettiCloudEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud binary sensor entities."""
    coordinator: BluettiCloudCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BluettiCloudOnlineSensor] = []
    for sn in entry.data.get("devices", []):
        entities.append(BluettiCloudOnlineSensor(coordinator, sn))

    async_add_entities(entities)


class BluettiCloudOnlineSensor(BluettiCloudEntity, BinarySensorEntity):
    """Binary sensor indicating whether the device is online."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Online"

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
    ) -> None:
        super().__init__(coordinator, device_sn, "online")

    @property
    def is_on(self) -> bool:
        return self.device_data.get("online", False)
