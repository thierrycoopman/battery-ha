"""Base entity for Bluetti Cloud integration."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator, is_device_reachable


class BluettiCloudEntity(CoordinatorEntity[BluettiCloudCoordinator]):
    """Base entity for all Bluetti Cloud entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        device_sn: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_{key}"

        # Build device info from whatever we have at init time.
        # The coordinator may not have data yet during first setup,
        # so use device_info from config as fallback.
        device_data = (coordinator.data or {}).get(device_sn, {})
        info = coordinator._device_info.get(device_sn, {})

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=device_data.get("device_name") or info.get("name", device_sn),
            manufacturer="Bluetti",
            model=device_data.get("device_type") or info.get("model", ""),
            serial_number=device_sn,
        )

    def set_optimistic(self, key: str, value: Any) -> None:
        """Record a value we just wrote so the UI holds it until confirmed.

        Writing only to _attr_* is not enough: the entity properties read from
        the coordinator's device data, which still holds the pre-write value —
        so the UI would snap back within a second and the change would look
        like it never registered. The device overwrites this on its next state
        report.
        """
        data = self.coordinator.data
        if data and self._device_sn in data:
            data[self._device_sn][key] = value

    @property
    def device_data(self) -> dict[str, Any]:
        """Return the coordinator data for this device."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._device_sn, {})

    @property
    def available(self) -> bool:
        """True while the device has been heard from recently enough to trust.

        Brief staleness is tolerated — cloud data lags and a missed poll is
        normal — but a device that has gone quiet for a long stretch (powered
        off, unplugged, off the network) should not keep presenting hours-old
        readings as current.
        """
        if not super().available or self.coordinator.data is None:
            return False
        device_data = self.coordinator.data.get(self._device_sn)
        if device_data is None:
            return False
        return is_device_reachable(device_data)


class BluettiSubDeviceEntity(CoordinatorEntity[BluettiCloudCoordinator]):
    """Base for entities belonging to an expansion connected to a main unit.

    Each expansion — a battery such as a B300 or B300K, or a hub such as the
    D1 (DC) or A1 (AC) — is registered as its own Home Assistant device, linked
    to the main unit via `via_device`. That keeps a growing setup navigable and
    lets a dashboard target one expansion directly, instead of every entity
    piling into a single flat list on the parent.

    The Modbus slave address is the stable identity: two batteries of the same
    model never collide, and an expansion keeps its entities across restarts.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BluettiCloudCoordinator,
        parent_sn: str,
        slave_addr: int,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_sn = parent_sn
        self._slave_addr = slave_addr
        self._attr_unique_id = f"{parent_sn}_node_{slave_addr}_{key}"

        node = self.node
        name = node.get("model_name") or f"Expansion {slave_addr}"
        # The main unit's own node carries its internal battery; name it for
        # what it is rather than repeating the parent's model.
        if slave_addr == 0 and node.get("has_battery"):
            name = "Internal Battery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{parent_sn}_node_{slave_addr}")},
            via_device=(DOMAIN, parent_sn),
            name=name,
            manufacturer="Bluetti",
            model=name,
            serial_number=node.get("sn") or None,
        )

    @property
    def parent_data(self) -> dict[str, Any]:
        """Coordinator data for the main unit this expansion is attached to."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._device_sn, {})

    @property
    def node(self) -> dict[str, Any]:
        """The node record for this expansion, or {} if it is not reported."""
        for node in self.parent_data.get("nodes", []):
            if node.get("slave_addr") == self._slave_addr:
                return node
        return {}

    @property
    def available(self) -> bool:
        """Available while the main unit still reports this expansion."""
        return bool(self.node)
