"""Base entity for Bluetti Cloud integration."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator


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
        """Return True if coordinator has run and device has data.

        We do NOT require the device to be "online" — cloud data may be
        slightly stale but still valid. Sensors should show last known values
        rather than going unavailable.
        """
        return (
            super().available
            and self.coordinator.data is not None
            and self._device_sn in self.coordinator.data
        )
