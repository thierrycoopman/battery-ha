"""End-to-end replay of realistic MQTT traffic.

Each test here reproduces a defect that reached a release. They all share a
shape: the individual parsers were correct, but a frame reached the wrong one.
Driving real captured bytes through the whole path is what exposes that, which
is why these start from the wire rather than from a parsed dict.
"""

from __future__ import annotations

import asyncio
import pathlib
from unittest.mock import MagicMock

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    INV_GRID_INFO,
    PACK_CELL_INFO,
    PACK_ITEM_INFO,
    PACK_ITEM_INFO_COUNT_V2,
)
from tests.replay import ReplaySession, error_response, fc03_response

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex300"
BLOCKS = FIXTURES / "blocks"

# The captured system: the main unit, a D1 hub and a B300 battery.
MAIN, HUB, BATTERY = 0, 11, 51


def block(addr: int) -> bytes:
    return bytes.fromhex((BLOCKS / f"block_{addr}.hex").read_text().strip())


def node_info() -> bytes:
    return bytes.fromhex((FIXTURES / "node_info_v1.hex").read_text().strip())


@pytest.fixture
def session() -> ReplaySession:
    """A session that has already discovered its expansions, as a live one has."""
    s = ReplaySession()
    s.discover_nodes(node_info())
    return s


def test_real_cell_block_decodes_to_a_healthy_pack(session):
    """The 16-cell capture, straight off the wire.

    A 50-byte cell block was once decoded with the 208-byte pack layout,
    reporting 3284 °C and 252 % charge. Anchoring on the real numbers means a
    routing mistake shows up as an implausible value, not a silent pass.
    """
    session.push_fc03(block(PACK_CELL_INFO), slave=BATTERY)

    node = next(n for n in session.nodes if n["slave_addr"] == BATTERY)
    assert node["cell_count"] == 16
    assert 3.0 < node["cell_voltage_min"] <= node["cell_voltage_max"] < 3.7
    # A balanced pack: the spread is what the dashboard treats as health.
    assert node["cell_voltage_delta"] < 0.05


def test_a_frame_from_slave_zero_is_the_main_unit_not_a_missing_address(session):
    """Slave 0 is falsy in Python, and the internal battery was lost to that.

    The main unit reports its own pack at its own address, and those readings
    belong to the main device rather than to an expansion. A truthiness test
    dropped every one of those frames.
    """
    session.push_fc03(block(PACK_CELL_INFO), slave=MAIN)

    assert session.data["cell_count"] == 16
    assert session.data["cell_voltage_delta"] < 0.05


def test_an_unsolicited_frame_is_never_mistaken_for_an_answer(session):
    """Telemetry arriving mid-poll must not be handed to the waiting reader.

    This hardware streams unprompted. The old single pending-request slot
    treated whatever arrived next as the reply, which is how a cell block came
    to be decoded as a pack record.
    """
    session.manager._pending_request = (PACK_ITEM_INFO, BATTERY)
    session.push_fc03(block(PACK_CELL_INFO), slave=BATTERY)

    node = next(n for n in session.nodes if n["slave_addr"] == BATTERY)
    # Decoded as cells — the length identifies it, not the outstanding request.
    assert node["cell_count"] == 16
    assert "pack_serial" not in node


def test_an_unidentifiable_frame_is_dropped_rather_than_guessed(session):
    """Guessing homeData for anything unrecognised produced battery_soc=12336.

    0x3030 is ASCII "00" — two characters of a serial number read as a
    percentage. Leaving the value absent is correct; inventing one is not.
    """
    session.push_fc03(bytes(96))

    assert "battery_soc" not in session.data
    # The frame still proves the device is alive, which availability depends on.
    assert "last_seen" in session.data


def test_a_corrupt_frame_is_dropped_before_it_can_be_decoded(session):
    """CRC is the only defence against a truncated or mangled payload."""
    good = fc03_response(block(PACK_CELL_INFO), slave=BATTERY)
    session.deliver(good[:-1] + bytes([good[-1] ^ 0xFF]))

    assert session.unparseable, "a bad CRC must not reach the parsers"
    assert "cell_count" not in next(
        n for n in session.nodes if n["slave_addr"] == BATTERY
    )


def test_a_realistic_burst_lands_every_block_where_it_belongs(session):
    """The device sends dozens of blocks per minute, interleaved and unasked.

    Replaying a burst is the closest thing to the live device available without
    taking the account's single MQTT session away from Home Assistant.
    """
    session.push_fc16(INV_GRID_INFO, block(INV_GRID_INFO))
    session.push_fc03(block(PACK_CELL_INFO), slave=BATTERY)
    session.push_fc16(1200, block(1200))
    session.push_fc03(block(PACK_CELL_INFO), slave=MAIN)
    session.push_fc16(1400, block(1400))

    assert session.data["grid_import_energy"] == 3.3
    assert session.data["pv_dc_string_count"] == 2
    assert session.data["ac_load_power"] == 0
    # The expansion kept its own reading; the main unit's went to the main unit.
    battery = next(n for n in session.nodes if n["slave_addr"] == BATTERY)
    assert battery["cell_count"] == 16
    assert session.data["cell_count"] == 16
    # The hub reports no pack, and must not have acquired one.
    hub = next(n for n in session.nodes if n["slave_addr"] == HUB)
    assert "cell_count" not in hub


def test_streaming_traffic_does_not_erase_earlier_readings(session):
    """Each block carries only its own fields; the rest must survive.

    Blocks arrive at different rates, so a merge that replaced the overlay
    would make every entity flicker between known and unknown.
    """
    session.push_fc16(INV_GRID_INFO, block(INV_GRID_INFO))
    for _ in range(5):
        session.push_fc16(1200, block(1200))

    assert session.data["grid_import_energy"] == 3.3


@pytest.mark.asyncio
async def test_a_poll_is_not_satisfied_by_unrelated_streaming_traffic(session):
    """The bug that made polls meaningless on a device that streams.

    A single shared event was set by *any* incoming frame. On the APEX 300,
    which pushes telemetry constantly, that meant every read returned
    immediately — the loop fired its next request straight away, believing an
    answer had arrived, and the block it actually asked for was never stored.
    """
    manager = session.manager
    manager._mqtt_client = MagicMock(is_connected=True)

    poll = asyncio.create_task(
        manager._poll_register(
            session.sn, "AP300", "2616113487436",
            PACK_ITEM_INFO, PACK_ITEM_INFO_COUNT_V2,
            slave_addr=BATTERY, payload_ver=1.2,
        )
    )
    await asyncio.sleep(0)

    # Unrelated telemetry keeps arriving, as it does on real hardware: pushes
    # of other blocks, and unsolicited reads from a different pack. The latter
    # is what the old code accepted as an answer — any FC=03 frame at all
    # released the wait, regardless of who sent it or how big it was.
    for _ in range(5):
        session.push_fc16(INV_GRID_INFO, block(INV_GRID_INFO))
        session.push_fc03(block(PACK_CELL_INFO), slave=MAIN)
        await asyncio.sleep(0)

    assert not poll.done(), "streaming traffic must not answer an outstanding read"

    # The reply it actually asked for — same address, expected size.
    session.push_fc03(bytes(PACK_ITEM_INFO_COUNT_V2 * 2), slave=BATTERY)
    await asyncio.wait_for(poll, timeout=1)


@pytest.mark.asyncio
async def test_a_refused_register_releases_the_poll_immediately(session):
    """A refusal is an answer. Waiting out the timeout wastes the poll cycle."""
    manager = session.manager
    manager._mqtt_client = MagicMock(is_connected=True)

    poll = asyncio.create_task(
        manager._poll_register(
            session.sn, "AP300", "2616113487436",
            PACK_ITEM_INFO, PACK_ITEM_INFO_COUNT_V2,
            slave_addr=BATTERY, payload_ver=1.2,
        )
    )
    await asyncio.sleep(0)

    session.deliver(error_response(0x03, 0x02, slave=BATTERY))
    await asyncio.wait_for(poll, timeout=1)

    # And the integration remembers not to ask again.
    assert (PACK_ITEM_INFO, BATTERY) in manager._unsupported_registers[session.sn]


@pytest.mark.asyncio
async def test_a_dropped_connection_releases_every_waiting_poll(session):
    """Otherwise the loop blocks for a full timeout per read on a dead link."""
    manager = session.manager
    manager._mqtt_client = MagicMock(is_connected=True)

    polls = [
        asyncio.create_task(
            manager._poll_register(
                session.sn, "AP300", "2616113487436",
                PACK_ITEM_INFO, PACK_ITEM_INFO_COUNT_V2,
                slave_addr=slave, payload_ver=1.2,
            )
        )
        for slave in (MAIN, BATTERY)
    ]
    await asyncio.sleep(0)

    manager._cleanup_mqtt_client()

    await asyncio.wait_for(asyncio.gather(*polls), timeout=1)
