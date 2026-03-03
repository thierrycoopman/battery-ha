"""Switch platform for Bluetti Cloud integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
from .entity import BluettiCloudEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BluettiSwitchDescription(SwitchEntityDescription):
    """Describes a Bluetti switch."""

    data_key: str
    fn_code: str


SWITCH_DESCRIPTIONS: list[BluettiSwitchDescription] = [
    BluettiSwitchDescription(
        key="ac_switch",
        data_key="ac_switch",
        fn_code="SetCtrlAcSwitch",
        name="AC Output",
        icon="mdi:power-plug",
    ),
    BluettiSwitchDescription(
        key="dc_switch",
        data_key="dc_switch",
        fn_code="SetCtrlDcSwitch",
        name="DC Output",
        icon="mdi:current-dc",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud switch entities."""
    coordinator: BluettiCloudCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BluettiCloudSwitch] = []
    for sn in entry.data.get("devices", []):
        for description in SWITCH_DESCRIPTIONS:
            entities.append(BluettiCloudSwitch(coordinator, sn, description))

    async_add_entities(entities)


class BluettiCloudSwitch(BluettiCloudEntity, SwitchEntity):
    """Bluetti Cloud switch entity for AC/DC output control."""

    entity_description: BluettiSwitchDescription

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        description: BluettiSwitchDescription,
    ) -> None:
        super().__init__(coordinator, device_sn, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.device_data.get(self.entity_description.data_key, False)

    @property
    def available(self) -> bool:
        """Switch is only available when device is online."""
        return super().available and self.device_data.get("online", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.control_device(
            self._device_sn, self.entity_description.fn_code, "1"
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.control_device(
            self._device_sn, self.entity_description.fn_code, "0"
        )
        await self.coordinator.async_request_refresh()
