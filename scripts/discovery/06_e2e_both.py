"""Phase 3 Task 5 — end-to-end live test (read-only).

Drives the REAL BluettiCloudCoordinator REST path against the live account for
both devices and prints the resolved per-device entity data. Validates profile
resolution (AC300 = mqtt+rest, AP300 = rest_only) and the AP300 REST field
mapping (voltage, charging status, switch states) end to end.

No control commands. MQTT is not started here (this exercises the REST path);
the AC300 therefore shows its REST baseline, which is offline/empty by design —
the AC300 needs MQTT for live data. The AP300 is fully populated over REST.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.coordinator import BluettiCloudCoordinator

FIELDS = [
    "online", "iot_session", "battery_soc", "pack_voltage", "charging_status",
    "power_pv_in", "power_grid_in", "power_ac_out", "power_dc_out",
    "ac_switch", "dc_switch", "pv_switch", "grid_switch",
    "energy_total",
]


async def main() -> None:
    email, password = get_credentials()
    async with aiohttp.ClientSession() as session:
        client = BluettiCloudApi(session)
        await client.login(email, password)

        devices = await client.get_devices()
        sns = [d["sn"] for d in devices]
        device_info = {
            d["sn"]: {"name": d.get("name", d["sn"]), "model": d.get("model", "")}
            for d in devices
        }
        print(f"Configured devices: {sns}")

        hass = MagicMock()
        hass.loop = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "e2e"
        with patch("homeassistant.helpers.frame.report_usage"):
            coordinator = BluettiCloudCoordinator(
                hass, entry, client, sns, device_info
            )

        data = await coordinator._async_update_data()

        for sn in sns:
            dev = data[sn]
            profile = coordinator.profile_for(sn)
            print(f"\n######## {dev['device_name']} ({dev['device_type']}) / {sn} ########")
            print(f"  profile.data_path = {profile.data_path}  controllable={profile.controllable}")
            for f in FIELDS:
                print(f"  {f:18s} = {dev.get(f)}")


if __name__ == "__main__":
    asyncio.run(main())
