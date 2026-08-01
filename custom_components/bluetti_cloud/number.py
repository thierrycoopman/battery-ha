"""Number platform for Bluetti Cloud — ECO mode parameters.

ECO mode turns an output off after it has drawn less than a threshold for a
set time. Each output has two knobs: how long to wait (hours) and what counts
as idle (watts). Ranges match what the device's own app enforces; values
outside them are refused rather than written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.modbus import (
    AC_ECO_AUTO_OFF_HOURS,
    AC_ECO_POWER,
    DC_ECO_AUTO_OFF_HOURS,
    DC_ECO_POWER,
    SETTING_RANGES,
)
from .api.mqtt_client import BluettiMqttError
from .coordinator import BluettiCloudCoordinator, BluettiConfigEntry
from .entity import BluettiCloudEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BluettiNumberDescription(NumberEntityDescription):
    """Describes a Bluetti numeric setting."""

    data_key: str
    register: int


ECO_NUMBER_DESCRIPTIONS: list[BluettiNumberDescription] = [
    BluettiNumberDescription(
        key="ac_eco_auto_off",
        data_key="ac_eco_auto_off",
        name="AC ECO Auto-Off",
        register=AC_ECO_AUTO_OFF_HOURS,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:timer-outline",
    ),
    BluettiNumberDescription(
        key="ac_eco_power",
        data_key="ac_eco_power",
        name="AC ECO Power Threshold",
        register=AC_ECO_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:flash-outline",
    ),
    BluettiNumberDescription(
        key="dc_eco_auto_off",
        data_key="dc_eco_auto_off",
        name="DC ECO Auto-Off",
        register=DC_ECO_AUTO_OFF_HOURS,
        native_unit_of_measurement=UnitOfTime.HOURS,
        icon="mdi:timer-outline",
    ),
    BluettiNumberDescription(
        key="dc_eco_power",
        data_key="dc_eco_power",
        name="DC ECO Power Threshold",
        register=DC_ECO_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        icon="mdi:flash-outline",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BluettiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bluetti Cloud number entities."""
    coordinator = entry.runtime_data

    entities: list[BluettiCloudNumber] = []
    for sn in entry.data.get("devices", []):
        if not coordinator.profile_for(sn).has_eco:
            continue
        for description in ECO_NUMBER_DESCRIPTIONS:
            entities.append(BluettiCloudNumber(coordinator, sn, description))

    async_add_entities(entities)


class BluettiCloudNumber(BluettiCloudEntity, NumberEntity):
    """A numeric device setting, bounded by the range the device accepts."""

    entity_description: BluettiNumberDescription
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        description: BluettiNumberDescription,
    ) -> None:
        super().__init__(coordinator, device_sn, description.key)
        self.entity_description = description
        low, high = SETTING_RANGES[description.register]
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = 1

    @property
    def native_value(self) -> float | None:
        value = self.device_data.get(self.entity_description.data_key)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Write the setting to the device."""
        desc = self.entity_description
        model = self.device_data.get("device_type", "")
        sub_sn = self.device_data.get("sub_sn", "")
        if not model or not sub_sn:
            _LOGGER.error("Cannot set %s: missing model or sub_sn", desc.name)
            return

        mqtt = self.coordinator.mqtt_client
        if not mqtt or not mqtt.is_connected:
            raise BluettiMqttError("MQTT not connected")

        profile = self.coordinator.profile_for(self._device_sn)
        mqtt.send_setting(
            model, sub_sn, desc.register, int(value),
            slave_addr=profile.slave_addr,
            payload_ver=profile.iot_payload_ver,
        )
        _LOGGER.info("Set %s to %s (reg=%d)", desc.name, int(value), desc.register)

        # Optimistic update, confirmed by the device's next state push.
        self._attr_native_value = value
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"register": self.entity_description.register}
