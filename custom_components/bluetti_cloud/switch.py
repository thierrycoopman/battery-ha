"""Switch platform for Bluetti Cloud integration.

Provides AC/DC output switches that read state from cloud telemetry
and send control commands via the coordinator's shared MQTT client.
Uses optimistic state updates for responsive UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.modbus import AC_SWITCH, DC_SWITCH, SWITCH_OFF, SWITCH_ON
from .api.mqtt_client import BluettiMqttError
from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator
from .entity import BluettiCloudEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BluettiSwitchDescription(SwitchEntityDescription):
    """Describes a Bluetti switch."""

    data_key: str
    register: int
    on_value: int
    off_value: int


SWITCH_DESCRIPTIONS: list[BluettiSwitchDescription] = [
    BluettiSwitchDescription(
        key="ac_switch",
        data_key="ac_switch",
        name="AC Output",
        icon="mdi:power-plug",
        register=AC_SWITCH,
        on_value=SWITCH_ON,
        off_value=SWITCH_OFF,
    ),
    BluettiSwitchDescription(
        key="dc_switch",
        data_key="dc_switch",
        name="DC Output",
        icon="mdi:current-dc",
        register=DC_SWITCH,
        on_value=SWITCH_ON,
        off_value=SWITCH_OFF,
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
    """Bluetti Cloud switch entity for AC/DC output control.

    Uses the coordinator's shared MQTT client for commands.
    Applies optimistic state updates for responsive UI, confirmed
    by MQTT write echo or next REST poll.
    """

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
    def is_on(self) -> bool | None:
        return self.device_data.get(self.entity_description.data_key)

    async def _send_switch_command(self, value: int) -> None:
        """Send a switch command via the coordinator's MQTT client."""
        desc = self.entity_description
        model = self.device_data.get("device_type", "")
        sub_sn = self.device_data.get("sub_sn", "")

        if not model or not sub_sn:
            _LOGGER.error(
                "Cannot control %s: missing model (%s) or sub_sn (%s)",
                desc.name, model, sub_sn,
            )
            return

        mqtt = self.coordinator.mqtt_client
        if not mqtt or not mqtt.is_connected:
            _LOGGER.error("MQTT not connected — cannot send %s command", desc.name)
            raise BluettiMqttError("MQTT not connected")

        try:
            mqtt.send_command(model, sub_sn, desc.register, value)
            _LOGGER.info(
                "Sent %s %s command to %s/%s (reg=%d val=%d)",
                desc.name,
                "ON" if value == desc.on_value else "OFF",
                model, sub_sn, desc.register, value,
            )
        except BluettiMqttError as err:
            _LOGGER.error("MQTT command failed for %s: %s", desc.name, err)
            raise

        # Optimistic update — assume command succeeded for responsive UI.
        # Will be confirmed/corrected by MQTT write echo or next REST poll.
        self._attr_is_on = value == desc.on_value
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._send_switch_command(self.entity_description.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._send_switch_command(self.entity_description.off_value)
