"""Bluetti Cloud integration for Home Assistant.

Uses the Bluetti mobile app API (reverse-engineered) to provide cloud-based
monitoring and control for Bluetti power stations, including models not
supported by the official HA integration (e.g., AC300).

Architecture: MQTT+REST hybrid
- MQTT provides real-time telemetry (~1s) for battery, pack, and switch data
- REST API provides power readings, energy totals, and online status (60s)
- If MQTT fails, falls back to REST-only mode (30s polling)
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import BluettiCloudApi
from .const import DOMAIN
from .coordinator import BluettiCloudCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bluetti Cloud from a config entry."""
    session = async_get_clientsession(hass)
    client = BluettiCloudApi(session)

    await client.login(entry.data["username"], entry.data["password"])

    device_sns = entry.data.get("devices", [])
    device_info = entry.data.get("device_info", {})

    coordinator = BluettiCloudCoordinator(
        hass, entry, client, device_sns, device_info
    )
    await coordinator.async_config_entry_first_refresh()

    # Start MQTT for real-time telemetry (non-blocking — REST works without it)
    try:
        await coordinator.async_start_mqtt()
    except Exception:
        _LOGGER.warning(
            "MQTT telemetry unavailable — using REST-only mode (30s polling)",
            exc_info=True,
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Bluetti Cloud config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: BluettiCloudCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_stop_mqtt()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok
