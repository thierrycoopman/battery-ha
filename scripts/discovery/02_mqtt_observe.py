"""Phase 1 Task 2 — passive MQTT observation (read-only).

Connects to the Bluetti IoT broker, subscribes to the device's PUB topic,
and logs every frame it receives WITHOUT sending any read or write. This
reveals whether the device pushes telemetry unprompted (like the AC300's
FC=16 pushes) or stays silent until polled.

DEVICE_SN / MODEL come from Task 1.1 (AP300 = APEX 300).
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.mqtt_client import BluettiMqttClient

DEVICE_SN = "AP3002616113487436"
MODEL = "AP300"
OBSERVE_SECONDS = 90

_count = 0


def on_telemetry(topic: str, parsed: dict) -> None:
    global _count
    _count += 1
    fc = parsed.get("function_code")
    data = parsed.get("data", b"")
    print(f"[PUSH #{_count}] {topic} FC={fc} len={len(data)} data={data.hex()}")


async def main() -> None:
    email, password = get_credentials()
    sub_sn = DEVICE_SN.removeprefix(MODEL)
    print(f"Model={MODEL} SN={DEVICE_SN} subSn={sub_sn}")

    async with aiohttp.ClientSession() as session:
        api = BluettiCloudApi(session)
        await api.login(email, password)
        print("Login OK")

        loop = asyncio.get_running_loop()
        mqtt = BluettiMqttClient(session, api._token, loop, on_telemetry)
        prep = await mqtt.async_prepare()
        await loop.run_in_executor(None, mqtt.connect_blocking, prep)
        print("MQTT connected")

        mqtt.subscribe_telemetry(MODEL, sub_sn)
        print(f"Subscribed to PUB/{MODEL}/{sub_sn}; observing {OBSERVE_SECONDS}s...")
        await asyncio.sleep(OBSERVE_SECONDS)

        print(f"Observed {_count} unprompted frame(s)")
        mqtt.disconnect()
        mqtt.cleanup_pem_files()
        print("Done")


if __name__ == "__main__":
    asyncio.run(main())
