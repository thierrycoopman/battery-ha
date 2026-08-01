"""Phase 4 (#4) — validate AP300 MQTT telemetry over the integration's own path.

Uses the shipped BluettiMqttClient.send_read_request with the AP300 profile's
payload_ver (1.2) and slave_addr (0), and the shipped parse_mqtt_payload +
parse_home_data, to confirm real-time telemetry works end to end. Read-only.

The broker rate-limits rapid reconnects, so this cools down first.
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import parse_home_data
from bluetti_cloud.api.mqtt_client import BluettiMqttClient, BluettiMqttError
from bluetti_cloud.api.profiles import get_profile

MODEL, SN, SUB = "AP300", "AP3002616113487436", "2616113487436"

_got: list[dict] = []


def on_telemetry(topic: str, parsed: dict) -> None:
    if parsed.get("function_code") == 0x03 and parsed.get("register_data"):
        home = parse_home_data(parsed["register_data"])
        _got.append(home)
        print(
            f"[TELEMETRY] soc={home.get('battery_soc')}% "
            f"voltage={home.get('pack_voltage')}V "
            f"status={home.get('charging_status')} "
            f"packs={home.get('pack_count')} "
            f"ac={home.get('ctrl_ac_switch')} dc={home.get('ctrl_dc_switch')}"
        )


async def main() -> None:
    profile = get_profile(MODEL, 2015)
    print(f"profile: data_path={profile.data_path} slave={profile.slave_addr} "
          f"payload_ver={profile.iot_payload_ver}")

    print("cooldown 40s (broker rate-limit)...")
    await asyncio.sleep(40)

    email, password = get_credentials()
    async with aiohttp.ClientSession() as session:
        api = BluettiCloudApi(session)
        await api.login(email, password)
        loop = asyncio.get_running_loop()
        mq = BluettiMqttClient(session, api._token, loop, on_telemetry)

        for attempt in range(3):
            try:
                prep = await mq.async_prepare()
                await loop.run_in_executor(None, mq.connect_blocking, prep)
                break
            except BluettiMqttError as err:
                print(f"connect attempt {attempt + 1} failed: {err}; cooldown 40s")
                await asyncio.sleep(40)
        else:
            print("could not connect")
            return

        mq.subscribe_telemetry(MODEL, SUB)
        print(f"connected + subscribed PUB/{MODEL}/{SUB}")
        await asyncio.sleep(1.5)

        for cycle in range(3):
            print(f"-> poll cycle {cycle + 1}: homeData reg=100")
            mq.send_read_request(
                MODEL, SUB, 100, 62,
                slave_addr=profile.slave_addr,
                payload_ver=profile.iot_payload_ver,
            )
            await asyncio.sleep(5)

        mq.disconnect()
        mq.cleanup_pem_files()
        print(f"\nReceived {len(_got)} telemetry frame(s) — "
              f"{'PASS' if _got else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
