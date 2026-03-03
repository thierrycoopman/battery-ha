"""Base entity for Bluetti Cloud integration."""

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

        device_data = coordinator.data.get(device_sn, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_sn)},
            name=device_data.get("device_name", device_sn),
            manufacturer="Bluetti",
            model=device_data.get("device_type", ""),
        )

    @property
    def device_data(self) -> dict:
        """Return the coordinator data for this device."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(self._device_sn, {})

    @property
    def available(self) -> bool:
        """Return True if coordinator has data and device entry exists."""
        return super().available and self._device_sn in (self.coordinator.data or {})
