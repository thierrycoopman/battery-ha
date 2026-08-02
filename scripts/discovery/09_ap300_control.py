"""Phase 4 (#4) — live AC/DC output control test for a V2 device.

**THIS PHYSICALLY SWITCHES THE DEVICE'S OUTPUTS.** Make sure nothing critical is
connected before running it.

For each output it: reads the current state, toggles to the opposite, waits,
restores the original state, and verifies the restore. Uses the shipped
send_command path (guarded allowlist, V2 registers 2011/2012, slave 0,
iotPayloadVer 1.2).
"""

from __future__ import annotations

import asyncio

import aiohttp
from _common import get_credentials

from bluetti_cloud.api.client import BluettiCloudApi
from bluetti_cloud.api.modbus import (
    INV_BASE_SETTINGS,
    INV_BASE_SETTINGS_COUNT,
    parse_inv_base_settings,
)
from bluetti_cloud.api.mqtt_client import BluettiMqttClient, BluettiMqttError
from bluetti_cloud.api.profiles import get_profile

MODEL, SUB = "AP300", "2616113487436"
SETTLE = 6  # seconds to wait for the device to act and report back

_state: dict[str, bool | None] = {"ac": None, "dc": None}


def on_telemetry(topic: str, parsed: dict) -> None:
    if parsed.get("function_code") == 0x03 and parsed.get("register_data"):
        # Authoritative switch state comes from INV_BASE_SETTINGS (reg 2000),
        # not the homeData ctrl bits.
        settings = parse_inv_base_settings(parsed["register_data"])
        if settings and len(parsed["register_data"]) == INV_BASE_SETTINGS_COUNT * 2:
            _state["ac"] = settings["ctrl_ac_switch"]
            _state["dc"] = settings["ctrl_dc_switch"]


async def read_state(mq, profile) -> tuple[bool | None, bool | None]:
    """Poll INV_BASE_SETTINGS and return the (ac, dc) output states."""
    _state["ac"] = _state["dc"] = None
    mq.send_read_request(
        MODEL, SUB, INV_BASE_SETTINGS, INV_BASE_SETTINGS_COUNT,
        slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
    )
    for _ in range(10):
        await asyncio.sleep(0.5)
        if _state["ac"] is not None:
            break
    return _state["ac"], _state["dc"]


async def test_output(mq, profile, name: str, register: int, key: str) -> bool:
    """Toggle one output and restore it. Returns True if the restore verified."""
    before = (await read_state(mq, profile))[0 if key == "ac" else 1]
    print(f"\n=== {name} ===")
    print(f"  current state: {before}")
    if before is None:
        print(f"  SKIP — could not read {name} state")
        return False

    target = not before
    print(f"  >>> switching {name} {'ON' if target else 'OFF'} (reg {register})")
    mq.send_command(
        MODEL, SUB, register, 1 if target else 0,
        slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
    )
    await asyncio.sleep(SETTLE)

    after = (await read_state(mq, profile))[0 if key == "ac" else 1]
    changed = after == target
    print(f"  state after toggle: {after} — {'CHANGED' if changed else 'no change'}")

    print(f"  >>> restoring {name} to {'ON' if before else 'OFF'}")
    mq.send_command(
        MODEL, SUB, register, 1 if before else 0,
        slave_addr=profile.slave_addr, payload_ver=profile.iot_payload_ver,
    )
    await asyncio.sleep(SETTLE)

    restored = (await read_state(mq, profile))[0 if key == "ac" else 1]
    ok = restored == before
    print(f"  restored state: {restored} — {'OK' if ok else 'MISMATCH'}")
    if not ok:
        print(f"  !! {name} did not return to its original state ({before})")
    return changed and ok


async def main() -> None:
    profile = get_profile(MODEL, 2015)
    print(f"profile: controllable={profile.controllable} "
          f"ac={profile.ac_switch_reg} dc={profile.dc_switch_reg} "
          f"slave={profile.slave_addr} pver={profile.iot_payload_ver}")

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
                print(f"connect attempt {attempt + 1} failed: {err}")
                await asyncio.sleep(45)
        else:
            print("could not connect")
            return

        mq.subscribe_telemetry(MODEL, SUB)
        print("connected + subscribed")
        await asyncio.sleep(2)

        ac_ok = await test_output(mq, profile, "AC output", profile.ac_switch_reg, "ac")
        dc_ok = await test_output(mq, profile, "DC output", profile.dc_switch_reg, "dc")

        mq.disconnect()
        mq.cleanup_pem_files()
        print(f"\nRESULT: AC {'PASS' if ac_ok else 'FAIL'}, "
              f"DC {'PASS' if dc_ok else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
