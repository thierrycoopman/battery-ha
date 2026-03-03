"""Data update coordinator for Bluetti Cloud."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import BluettiCloudApi, BluettiCloudApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class BluettiCloudCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator that polls the Bluetti Cloud API for device data.

    Data structure:
        {
            "<device_sn>": {
                "online": bool,
                "device_name": str,
                "device_type": str,
                "battery_soc": int,
                "total_battery_percent": int,
                "power_pv_in": int,
                "power_grid_in": int,
                "power_ac_out": int,
                "power_dc_out": int,
                "ac_switch": bool,
                "dc_switch": bool,
                ...
            }
        }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: BluettiCloudApi,
        device_sns: list[str],
        device_info: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._client = client
        self._device_sns = device_sns
        self._device_info = device_info

    @property
    def client(self) -> BluettiCloudApi:
        return self._client

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from the Bluetti Cloud API."""
        try:
            all_devices = await self._client.get_devices()
        except BluettiCloudApiError as err:
            raise UpdateFailed(f"Error fetching device list: {err}") from err

        # Build a lookup from the device list
        device_lookup: dict[str, dict[str, Any]] = {}
        for dev in all_devices:
            sn = dev.get("deviceSn", "")
            if sn in self._device_sns:
                last_alive = dev.get("lastAlive") or {}
                info = self._device_info.get(sn, {})
                device_lookup[sn] = {
                    "online": bool(dev.get("online")),
                    "device_name": info.get("name", dev.get("deviceName", sn)),
                    "device_type": info.get("model", dev.get("productName", "")),
                    "battery_soc": last_alive.get("batterySoc"),
                    "total_battery_percent": last_alive.get("totalBatteryPercent"),
                    "power_pv_in": last_alive.get("powerPvIn"),
                    "power_grid_in": last_alive.get("powerGridIn"),
                    "power_ac_out": last_alive.get("powerAcOut"),
                    "power_dc_out": last_alive.get("powerDcOut"),
                    "ac_switch": bool(last_alive.get("acSwitch")),
                    "dc_switch": bool(last_alive.get("dcSwitch")),
                }

        # Fetch detailed telemetry for online devices
        for sn in self._device_sns:
            if sn in device_lookup and device_lookup[sn]["online"]:
                try:
                    alive_data = await self._client.get_device_last_alive(sn)
                    if alive_data:
                        device_lookup[sn].update({
                            "battery_soc": alive_data.get("batterySoc", device_lookup[sn]["battery_soc"]),
                            "total_battery_percent": alive_data.get("totalBatteryPercent", device_lookup[sn]["total_battery_percent"]),
                            "power_pv_in": alive_data.get("powerPvIn", device_lookup[sn]["power_pv_in"]),
                            "power_grid_in": alive_data.get("powerGridIn", device_lookup[sn]["power_grid_in"]),
                            "power_ac_out": alive_data.get("powerAcOut", device_lookup[sn]["power_ac_out"]),
                            "power_dc_out": alive_data.get("powerDcOut", device_lookup[sn]["power_dc_out"]),
                            "ac_switch": bool(alive_data.get("acSwitch", device_lookup[sn]["ac_switch"])),
                            "dc_switch": bool(alive_data.get("dcSwitch", device_lookup[sn]["dc_switch"])),
                        })
                except BluettiCloudApiError:
                    _LOGGER.warning("Failed to get live telemetry for %s", sn)
            elif sn not in device_lookup:
                # Device not in cloud response — mark as offline
                info = self._device_info.get(sn, {})
                device_lookup[sn] = {
                    "online": False,
                    "device_name": info.get("name", sn),
                    "device_type": info.get("model", ""),
                    "battery_soc": None,
                    "total_battery_percent": None,
                    "power_pv_in": None,
                    "power_grid_in": None,
                    "power_ac_out": None,
                    "power_dc_out": None,
                    "ac_switch": False,
                    "dc_switch": False,
                }

        return device_lookup
