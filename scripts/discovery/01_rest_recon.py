"""Phase 1 Task 1 — REST reconnaissance (read-only).

Logs in, lists every device on the account, and dumps model, protocolVer,
iotPayloadVer, extend fields, live telemetry, energy totals, and a
power-statistics sample for each. Nothing is written to any device.
"""

from __future__ import annotations

import asyncio
from datetime import date

import aiohttp
from _common import dump, get_credentials  # sets sys.path on import

from bluetti_cloud.api.client import BluettiCloudApi


async def main() -> None:
    email, password = get_credentials()
    async with aiohttp.ClientSession() as session:
        api = BluettiCloudApi(session)
        await api.login(email, password)
        print("Login OK")

        devices = await api.get_devices()
        dump("homeDevices (all)", devices)

        for dev in devices:
            sn = dev.get("sn", "")
            model = dev.get("model", "?")
            print(f"\n######## DEVICE {model} / {sn} ########")
            for key in ("protocolVer", "iotPayloadVer", "sessionState", "type"):
                print(f"{key}: {dev.get(key)}")

            # Extend fields (per-model extra attributes)
            try:
                ext = await api._request(
                    "GET",
                    "/api/blusmartprod/business/v1/getExtendFieldBySn",
                    params={"businessSn": sn},
                )
                dump(f"{sn} extendFields", ext)
            except Exception as err:  # noqa: BLE001 - discovery, keep going
                print(f"extendFields error: {err}")

            try:
                dump(f"{sn} getDeviceLastAlive", await api.get_device_last_alive(sn))
            except Exception as err:  # noqa: BLE001
                print(f"getDeviceLastAlive error: {err}")

            try:
                dump(f"{sn} energyDetail", await api.get_energy_detail(sn))
            except Exception as err:  # noqa: BLE001
                print(f"energyDetail error: {err}")

            try:
                dump(
                    f"{sn} powerStatistics {date.today().isoformat()}",
                    await api.get_power_statistics(sn, date.today().isoformat()),
                )
            except Exception as err:  # noqa: BLE001
                print(f"powerStatistics error: {err}")


if __name__ == "__main__":
    asyncio.run(main())
