"""Phase 4 — live ECO mode settings test for a V2 device.

ECO turns an output off after it has drawn less than a threshold for a set
time. This changes a device setting but does NOT switch any output, so it is
safe to exercise. Everything is restored at the end.

Reads the current ECO settings, writes new ones, verifies the device accepted
them, then puts the originals back and verifies again.
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import (
    AC_ECO_AUTO_OFF_HOURS,
    AC_ECO_MODE,
    AC_ECO_POWER,
    INV_BASE_SETTINGS,
    INV_BASE_SETTINGS_COUNT,
    parse_inv_base_settings,
)
from bluetti_cloud.api.mqtt_client import BluettiMqttClient, BluettiMqttError
from bluetti_cloud.api.profiles import get_profile

MODEL, SUB = "AP300", "2616113487436"
SETTLE = 6

_state: dict = {}


def on_telemetry(topic: str, parsed: dict) -> None:
    data = parsed.get("register_data", b"")
    if len(data) == INV_BASE_SETTINGS_COUNT * 2:
        settings = parse_inv_base_settings(data)
        if "ac_eco" in settings:
            _state.clear()
            _state.update(settings)


async def read_settings(mq, profile) -> dict:
    _state.clear()
    mq.send_read_request(
        MODEL, SUB, INV_BASE_SETTINGS, INV_BASE_SETTINGS_COUNT,
        slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
    )
    for _ in range(12):
        await asyncio.sleep(0.5)
        if _state:
            break
    return dict(_state)


def show(label: str, s: dict) -> None:
    print(f"  {label}: ac_eco={s.get('ac_eco')} "
          f"auto_off={s.get('ac_eco_auto_off')}h "
          f"power={s.get('ac_eco_power')}W", flush=True)


async def main() -> None:
    profile = get_profile(MODEL, 2015)
    print("cooldown 45s...", flush=True)
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
                print(f"connect attempt {attempt + 1}: {err}", flush=True)
                await asyncio.sleep(45)
        else:
            print("could not connect")
            return

        mq.subscribe_telemetry(MODEL, SUB)
        await asyncio.sleep(2)

        before = await read_settings(mq, profile)
        if not before:
            print("could not read ECO settings")
            mq.disconnect()
            return
        print("\n=== AC ECO ===")
        show("before", before)

        # Pick values that differ from the current ones, within device limits.
        want_on = not before.get("ac_eco")
        want_hours = 3 if before.get("ac_eco_auto_off") != 3 else 2
        want_power = 30 if before.get("ac_eco_power") != 30 else 20

        print(f"  >>> setting ac_eco={want_on} auto_off={want_hours}h "
              f"power={want_power}W", flush=True)
        mq.send_command(
            MODEL, SUB, AC_ECO_MODE, 1 if want_on else 0,
            slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
        )
        await asyncio.sleep(2)
        mq.send_setting(
            MODEL, SUB, AC_ECO_AUTO_OFF_HOURS, want_hours,
            slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
        )
        await asyncio.sleep(2)
        mq.send_setting(
            MODEL, SUB, AC_ECO_POWER, want_power,
            slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
        )
        await asyncio.sleep(SETTLE)

        after = await read_settings(mq, profile)
        show("after", after)
        ok = (
            after.get("ac_eco") == want_on
            and after.get("ac_eco_auto_off") == want_hours
            and after.get("ac_eco_power") == want_power
        )
        print(f"  accepted: {'YES' if ok else 'NO'}", flush=True)

        print("  >>> restoring originals", flush=True)
        mq.send_command(
            MODEL, SUB, AC_ECO_MODE, 1 if before.get("ac_eco") else 0,
            slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
        )
        await asyncio.sleep(2)
        for reg, key in ((AC_ECO_AUTO_OFF_HOURS, "ac_eco_auto_off"),
                         (AC_ECO_POWER, "ac_eco_power")):
            value = before.get(key)
            if value:
                mq.send_setting(
                    MODEL, SUB, reg, value,
                    slave_addr=profile.slave_addr,
                    payload_ver=profile.iot_payload_ver,
                )
                await asyncio.sleep(2)
        await asyncio.sleep(SETTLE)

        restored = await read_settings(mq, profile)
        show("restored", restored)
        same = all(
            restored.get(k) == before.get(k)
            for k in ("ac_eco", "ac_eco_auto_off", "ac_eco_power")
        )
        print(f"  restore clean: {'YES' if same else 'NO'}", flush=True)

        mq.disconnect()
        mq.cleanup_pem_files()
        print(f"\nRESULT: ECO settings {'PASS' if ok and same else 'FAIL'}")
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
