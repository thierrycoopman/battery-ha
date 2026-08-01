"""Select platform for Bluetti Cloud — charging mode.

Charging mode changes how hard the device charges: Standard is the default,
Silent trades speed for quieter operation, Turbo charges as fast as the
hardware allows, and Custom follows the device's user-configured limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.modbus import CHARGING_MODES
from .api.mqtt_client import BluettiMqttError
from .coordinator import BluettiCloudCoordinator, BluettiConfigEntry
from .entity import BluettiCloudEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BluettiSelectDescription(SelectEntityDescription):
    """Describes a Bluetti enum setting."""

    data_key: str


CHARGING_MODE_DESCRIPTION = BluettiSelectDescription(
    key="charging_mode",
    data_key="charging_mode_setting",
    name="Charging Mode",
    icon="mdi:battery-charging-medium",
    options=sorted(CHARGING_MODES.values()),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BluettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud select entities."""
    coordinator = entry.runtime_data

    entities: list[BluettiChargingModeSelect] = []
    for sn in entry.data.get("devices", []):
        if coordinator.profile_for(sn).charging_mode_reg is not None:
            entities.append(
                BluettiChargingModeSelect(coordinator, sn, CHARGING_MODE_DESCRIPTION)
            )

    async_add_entities(entities)


class BluettiChargingModeSelect(BluettiCloudEntity, SelectEntity):
    """Charging mode selector."""

    entity_description: BluettiSelectDescription

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        description: BluettiSelectDescription,
    ) -> None:
        super().__init__(coordinator, device_sn, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        return self.device_data.get(self.entity_description.data_key)

    async def async_select_option(self, option: str) -> None:
        """Write the selected charging mode to the device."""
        value = next(
            (code for code, name in CHARGING_MODES.items() if name == option), None
        )
        if value is None:
            _LOGGER.error("Unknown charging mode %r", option)
            return

        model = self.device_data.get("device_type", "")
        sub_sn = self.device_data.get("sub_sn", "")
        if not model or not sub_sn:
            _LOGGER.error("Cannot set charging mode: missing model or sub_sn")
            return

        mqtt = self.coordinator.mqtt_client
        if not mqtt or not mqtt.is_connected:
            raise BluettiMqttError("MQTT not connected")

        profile = self.coordinator.profile_for(self._device_sn)
        mqtt.send_setting(
            model, sub_sn, profile.charging_mode_reg, value,
            slave_addr=profile.slave_addr,
            payload_ver=profile.iot_payload_ver,
        )
        _LOGGER.info("Set charging mode to %s (%d)", option, value)

        # Optimistic update, confirmed by the device's next state push.
        self._attr_current_option = option
        self.async_write_ha_state()
