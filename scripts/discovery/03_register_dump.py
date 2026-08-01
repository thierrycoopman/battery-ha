"""Phase 1 Task 3 — FC=03 register dump (read-only).

Polls the known AC300 register blocks (homeData=100, packMainInfo=6000,
packItemInfo=6100) on the AP300 and prints raw + parsed results, trying both
slave addresses (1 = older, 0 = 2nd-gen IoT). Read-only: FC=03 only.

DEVICE_SN / MODEL from Task 1.1 (AP300 = APEX 300).
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import (
    HOME_DATA,
    HOME_DATA_COUNT,
    PACK_ITEM_INFO,
    PACK_ITEM_INFO_COUNT,
    PACK_MAIN_INFO,
    PACK_MAIN_INFO_COUNT,
    parse_home_data,
    parse_pack_item_info,
    parse_pack_main_info,
)
from bluetti_cloud.api.mqtt_client import BluettiMqttClient

DEVICE_SN = "AP3002616113487436"
MODEL = "AP300"

READS = [
    ("homeData", HOME_DATA, HOME_DATA_COUNT, parse_home_data),
    ("packMainInfo", PACK_MAIN_INFO, PACK_MAIN_INFO_COUNT, parse_pack_main_info),
    ("packItemInfo", PACK_ITEM_INFO, PACK_ITEM_INFO_COUNT, parse_pack_item_info),
]

_responses: list[dict] = []


def on_telemetry(topic: str, parsed: dict) -> None:
    fc = parsed.get("function_code")
    data = parsed.get("data", b"")
    tag = "ERROR" if fc and fc & 0x80 else "resp"
    print(f"[{tag}] {topic} FC=0x{fc:02x} len={len(data)} data={data.hex()}")
    _responses.append(parsed)


async def main() -> None:
    email, password = get_credentials()
    sub_sn = DEVICE_SN.removeprefix(MODEL)

    async with aiohttp.ClientSession() as session:
        api = BluettiCloudApi(session)
        await api.login(email, password)
        loop = asyncio.get_running_loop()
        mqtt = BluettiMqttClient(session, api._token, loop, on_telemetry)
        prep = await mqtt.async_prepare()
        await loop.run_in_executor(None, mqtt.connect_blocking, prep)
        mqtt.subscribe_telemetry(MODEL, sub_sn)
        await asyncio.sleep(1)

        for slave in (1, 0):
            print(f"\n### slave_addr={slave} ###")
            for name, reg, count, _parser in READS:
                print(f"-> read {name} reg={reg} count={count} slave={slave}")
                try:
                    mqtt.send_read_request(MODEL, sub_sn, reg, count, slave_addr=slave)
                except Exception as err:  # noqa: BLE001
                    print(f"   send error: {err}")
                await asyncio.sleep(2.5)

        await asyncio.sleep(1)
        mqtt.disconnect()
        mqtt.cleanup_pem_files()

        print("\n===== PARSED (best-effort with AC300 map) =====")
        for parsed in _responses:
            data = parsed.get("data", b"")
            fc = parsed.get("function_code")
            if fc and fc & 0x80:
                continue
            for name, _reg, count, parser in READS:
                if len(data) == count * 2:
                    try:
                        print(f"[{name} len={len(data)}]", parser(data))
                    except Exception as err:  # noqa: BLE001
                        print(f"[{name}] parse error: {err}")


if __name__ == "__main__":
    asyncio.run(main())
