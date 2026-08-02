"""Binary sensor platform for Bluetti Cloud integration."""

from __future__ import annotations

import time
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import (
    BluettiCloudCoordinator,
    BluettiConfigEntry,
    is_device_reachable,
)
from .entity import BluettiCloudEntity
from .subdevice import build_sub_device_entities


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
REACHABLE_DESCRIPTION = BluettiBinarySensorDescription(
    key="reachable",
    data_key="last_seen",
    name="Device Reachable",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    icon="mdi:access-point-network",
)

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
        entities.append(
            BluettiReachableBinarySensor(coordinator, sn, REACHABLE_DESCRIPTION)
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

    # Sub-device (NODE_INFO) connectivity sensors — batteries, D1/A1 hubs, the
    # inverter — created dynamically as nodes are discovered over MQTT.
    created_nodes: dict[str, set[int]] = {sn: set() for sn in entry.data.get("devices", [])}

    def _add_nodes(sn: str, nodes: list[dict]) -> None:
        if sn not in created_nodes:
            return
        new_entities: list = []
        for node in nodes:
            addr = node["slave_addr"]
            if addr in created_nodes[sn]:
                continue
            created_nodes[sn].add(addr)
            new_entities.extend(
                e for e in build_sub_device_entities(coordinator, sn, node)
                if isinstance(e, BinarySensorEntity)
            )
        if new_entities:
            async_add_entities(new_entities)

    for sn in entry.data.get("devices", []):
        _add_nodes(sn, coordinator.get_nodes(sn))
    coordinator.register_node_callback(_add_nodes)


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


class BluettiReachableBinarySensor(BluettiCloudBinarySensor):
    """Whether the device has been heard from recently.

    Reports reachability, not power state: the cloud API exposes no dependable
    power signal, so a device that is switched off and one that has lost its
    network connection look identical from here.
    """

    # Must stay available in order to report that the device is not.
    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self._device_sn in self.coordinator.data
        )

    @property
    def is_on(self) -> bool | None:
        """True if heard from recently, False if gone quiet, None if unknown.

        Some devices never provide a contact time; reporting them as reachable
        would be a claim we cannot support, so this stays unknown instead.
        """
        if not self.device_data.get("last_seen"):
            return None
        return is_device_reachable(self.device_data)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        last_seen = self.device_data.get("last_seen")
        if not last_seen:
            return {"last_seen": None}
        return {
            "last_seen": dt_util.utc_from_timestamp(last_seen).isoformat(),
            "seconds_since_contact": int(time.time() - last_seen),
        }
