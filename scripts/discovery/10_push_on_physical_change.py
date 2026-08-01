"""Does a physical state change on the device produce an unsolicited MQTT push?

Listens PASSIVELY — it never sends a read or write — and reports any frame that
arrives. While it runs, change something on the device itself (e.g. press the AC
output button). A frame arriving here proves the device pushes state changes
unprompted, which means the integration can react instantly instead of polling.

Run it, then press the button when it says LISTENING.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import (
    INV_BASE_SETTINGS,
    parse_home_data,
    parse_inv_base_settings,
)
from bluetti_cloud.api.mqtt_client import BluettiMqttClient, BluettiMqttError

MODEL, SUB = "AP300", "2616113487436"
LISTEN_SECONDS = 120

_t0 = 0.0
_frames: list[tuple[float, int, int | None]] = []


def on_telemetry(topic: str, parsed: dict) -> None:
    dt = time.time() - _t0
    fc = parsed.get("function_code")
    start = parsed.get("start_addr")
    data = parsed.get("register_data", b"")
    _frames.append((round(dt, 1), fc, start))

    detail = ""
    if start == INV_BASE_SETTINGS or (fc == 0x03 and len(data) == 60):
        s = parse_inv_base_settings(data)
        if s:
            detail = f"  ac={s['ctrl_ac_switch']} dc={s['ctrl_dc_switch']}"
    elif fc == 0x03 and len(data) == 124:
        h = parse_home_data(data)
        detail = f"  soc={h.get('battery_soc')} ac={h.get('ctrl_ac_switch')}"

    print(f"  [+{dt:6.1f}s] PUSH fc=0x{fc:02x} start_addr={start} "
          f"len={len(data)}{detail}", flush=True)


async def main() -> None:
    global _t0
    print("cooldown 45s (broker rate-limit)...", flush=True)
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
                print(f"connect attempt {attempt + 1} failed: {err}", flush=True)
                await asyncio.sleep(45)
        else:
            print("could not connect")
            return

        mq.subscribe_telemetry(MODEL, SUB)
        _t0 = time.time()
        print(f"\n>>> LISTENING for {LISTEN_SECONDS}s — press the AC (or DC) "
              f"button on the device now. Nothing is being sent from here.\n",
              flush=True)
        await asyncio.sleep(LISTEN_SECONDS)

        mq.disconnect()
        mq.cleanup_pem_files()
        print(f"\nFrames received while passive: {len(_frames)}")
        print("VERDICT: "
              + ("device PUSHES state changes unprompted"
                 if _frames else "no unsolicited pushes — polling required"))
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
