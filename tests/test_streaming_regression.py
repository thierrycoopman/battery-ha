"""Streaming must not suppress node and pack discovery.

The poll back-off exists because a streaming device already sends its telemetry
blocks unprompted. But sub-device discovery and per-pack reads are REQUESTS —
the device answers them, it does not volunteer them per pack. Skipping the whole
cycle while streaming left every expansion entity unavailable.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

SN = "AP3002616113487436"


def _manager():
    coordinator = MagicMock()
    coordinator.data = {SN: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    mgr = BluettiMqttManager(coordinator)
    mgr._mqtt_client = MagicMock(is_connected=True)
    mgr._mqtt_connected = True
    mgr.overlays[SN] = {"nodes": [
        {"slave_addr": 0, "model": 6, "model_name": "AP300",
         "is_battery": False, "online": True},
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]}
    return mgr


@pytest.mark.asyncio
async def test_streaming_device_still_discovers_its_expansions():
    mgr = _manager()
    mgr._note_push(SN)                      # device is streaming
    assert mgr.is_streaming(SN) is True

    queried: list = []
    mgr._mqtt_client.send_node_query = lambda *a, **k: queried.append("node")
    mgr._poll_register = AsyncMock()

    await mgr._poll_once(SN, "AP300", "X", AP300_PROFILE)

    assert queried, "node discovery must still run while streaming"


@pytest.mark.asyncio
async def test_streaming_device_still_reads_each_pack():
    mgr = _manager()
    mgr._note_push(SN)
    reads: list = []

    async def _record(sn, model, sub_sn, register, count, slave_addr=1, payload_ver=1.0):
        reads.append((register, slave_addr))

    mgr._poll_register = _record
    mgr._mqtt_client.send_node_query = lambda *a, **k: None

    await mgr._poll_once(SN, "AP300", "X", AP300_PROFILE)

    packs_read = {slave for reg, slave in reads if reg == 6100}
    assert packs_read == {0, 51}, "both packs must still be read while streaming"


@pytest.mark.asyncio
async def test_streaming_still_skips_the_redundant_telemetry_poll():
    """The saving the back-off was for is still made."""
    mgr = _manager()
    mgr._note_push(SN)
    reads: list = []

    async def _record(sn, model, sub_sn, register, count, slave_addr=1, payload_ver=1.0):
        reads.append(register)

    mgr._poll_register = _record
    mgr._mqtt_client.send_node_query = lambda *a, **k: None

    await mgr._poll_once(SN, "AP300", "X", AP300_PROFILE)

    assert 100 not in reads, "homeData is pushed; polling it too is redundant"


def test_pushed_pack_frame_is_attributed_by_its_own_slave_byte():
    """A push carries the sending pack's slave address; guessing from the last
    request would file a B300's data against the internal battery."""
    mgr = _manager()
    pack = bytearray(208)
    pack[27] = 94
    pack[105] = 16
    raw = b"B300" + b"\x00" * 8
    for i in range(6):
        pack[2 + i * 2] = raw[i * 2 + 1]
        pack[3 + i * 2] = raw[i * 2]

    mgr._pending_request = (6100, 0)      # last request was the OTHER pack
    mgr._handle_write_multiple_data(SN, {
        "function_code": 0x10,
        "start_addr": 6100,
        "register_data": bytes(pack),
        "slave_addr": 51,                  # but this frame came from the B300
    })

    by_addr = {n["slave_addr"]: n for n in mgr.overlays[SN]["nodes"]}
    assert by_addr[51].get("pack_soc") == 94
    assert "pack_soc" not in by_addr[0], "must not be filed against the wrong pack"
