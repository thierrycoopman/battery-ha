"""Phase 4 (#5) — validate NODE_INFO sub-device enumeration via the shipped path.

Uses the shipped BluettiMqttClient.send_node_query + parse_node_info to confirm
the device returns its sub-device list (batteries, D1/A1 hubs, inverter).
Read-only except the benign NODE_INFO query-write (selects what to report).
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import NODE_INFO, parse_node_info
from bluetti_cloud.api.mqtt_client import BluettiMqttClient, BluettiMqttError

MODEL, SUB = "AP300", "2616113487436"
_nodes: list = []


def on_telemetry(topic: str, parsed: dict) -> None:
    if parsed.get("function_code") == 0x10 and parsed.get("start_addr") == NODE_INFO:
        nodes = parse_node_info(parsed.get("register_data", b""))
        _nodes.extend(nodes)
        for n in nodes:
            print(f"[NODE] slave={n['slave_addr']:>3} {n['model_name']:<14} "
                  f"online={n['online']} battery={n['is_battery']} "
                  f"warn={n['warning']} err={n['error']}")


async def main() -> None:
    print("cooldown 45s (broker rate-limit)...")
    await asyncio.sleep(45)
    email, password = get_credentials()
    async with aiohttp.ClientSession() as session:
        api = BluettiCloudApi(session)
        await api.login(email, password)
        loop = asyncio.get_running_loop()
        mq = BluettiMqttClient(session, api._token, loop, on_telemetry)
        for attempt in range(4):
            try:
                prep = await mq.async_prepare()
                await loop.run_in_executor(None, mq.connect_blocking, prep)
                break
            except BluettiMqttError as err:
                print(f"connect attempt {attempt + 1} failed: {err}; cooldown 45s")
                await asyncio.sleep(45)
        else:
            print("could not connect")
            return
        mq.subscribe_telemetry(MODEL, SUB)
        print("connected + subscribed")
        await asyncio.sleep(2)
        print("-> NODE_INFO query (version 1)")
        mq.send_node_query(MODEL, SUB, 1, 1.2)
        await asyncio.sleep(6)
        mq.disconnect()
        mq.cleanup_pem_files()
        print(f"\nEnumerated {len(_nodes)} sub-device(s) — "
              f"{'PASS' if _nodes else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
