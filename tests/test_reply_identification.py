"""Identify a reply from the frame itself, not from what was last requested.

FC=03 replies carry no register address, and they can arrive after the pending
request has moved on. Their length identifies the block and their slave byte
identifies the pack, so both are read from the frame rather than assumed.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.modbus import (
    HOME_DATA,
    INV_BASE_SETTINGS,
    PACK_CELL_INFO,
    PACK_ITEM_INFO,
)
from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

PARENT = "AP3002616113487436"


def _manager():
    coordinator = MagicMock()
    coordinator.data = {PARENT: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    mgr = BluettiMqttManager(coordinator)
    mgr.overlays[PARENT] = {"nodes": [
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]}
    return mgr


def test_block_identified_by_payload_length():
    mgr = _manager()
    assert mgr.identify_block(208) == PACK_ITEM_INFO
    assert mgr.identify_block(124) == HOME_DATA
    assert mgr.identify_block(60) == INV_BASE_SETTINGS
    assert mgr.identify_block(44) == PACK_CELL_INFO
    assert mgr.identify_block(50) == PACK_CELL_INFO
    assert mgr.identify_block(7) is None


def test_reply_that_overtook_its_request_still_lands_correctly():
    """Pending says cells, but a pack-sized reply arrives — it must be parsed
    as a pack, using the slave byte from the frame."""
    mgr = _manager()
    mgr._pending_request = (PACK_CELL_INFO, 51)

    pack = bytearray(208)
    pack[27] = 94
    pack[105] = 16
    raw = b"B300" + b"\x00" * 8
    for i in range(6):
        pack[2 + i * 2] = raw[i * 2 + 1]
        pack[3 + i * 2] = raw[i * 2]

    mgr._handle_telemetry_data(PARENT, {
        "function_code": 0x03,
        "register_data": bytes(pack),
        "slave_addr": 51,
    })
    node = mgr.overlays[PARENT]["nodes"][0]
    assert node["pack_soc"] == 94
    assert node["pack_model"] == "B300"


def test_cell_reply_lands_on_the_pack_that_sent_it():
    mgr = _manager()
    mgr._pending_request = (PACK_ITEM_INFO, 51)  # deliberately mismatched
    cells = bytearray(50)
    cells[1] = 4
    cells[3] = 2
    for i, mv in enumerate((3300, 3310, 3305, 3302)):
        cells[4 + 2 * i] = (mv >> 8) & 0xFF
        cells[5 + 2 * i] = mv & 0xFF

    mgr._handle_telemetry_data(PARENT, {
        "function_code": 0x03,
        "register_data": bytes(cells),
        "slave_addr": 51,
    })
    node = mgr.overlays[PARENT]["nodes"][0]
    assert node["cell_count"] == 4
    assert node["cell_voltage_delta"] == 0.01
    # and it was NOT decoded as a pack record
    assert "pack_soc" not in node


def test_slave_zero_is_a_valid_address_not_a_missing_one():
    """The main unit answers at slave 0, and 0 is falsy — a truthiness check
    silently discarded its address and lost the internal battery."""
    coordinator = MagicMock()
    coordinator.data = {PARENT: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    mgr = BluettiMqttManager(coordinator)
    mgr.overlays[PARENT] = {"nodes": [
        {"slave_addr": 0, "model": 6, "model_name": "AP300",
         "is_battery": False, "online": True},
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]}

    pack = bytearray(208)
    pack[27] = 93
    raw = b"AP300" + b"\x00" * 7
    for i in range(6):
        pack[2 + i * 2] = raw[i * 2 + 1]
        pack[3 + i * 2] = raw[i * 2]

    mgr._handle_telemetry_data(PARENT, {
        "function_code": 0x03,
        "register_data": bytes(pack),
        "slave_addr": 0,
    })

    by_addr = {n["slave_addr"]: n for n in mgr.overlays[PARENT]["nodes"]}
    assert by_addr[0]["pack_soc"] == 93
    assert by_addr[0]["has_battery"] is True
    # and it must not have been misfiled onto the expansion
    assert "pack_soc" not in by_addr[51]


def test_settings_blocks_are_not_mistaken_for_cell_blocks():
    """The cell block is matched by size range, which overlaps the settings
    blocks — exact sizes must win so a 60-byte settings reply is never decoded
    as cells."""
    mgr = _manager()
    assert mgr.identify_block(60) == INV_BASE_SETTINGS   # not cells
    assert mgr.identify_block(40) != PACK_CELL_INFO      # adv settings
    assert mgr.identify_block(50) == PACK_CELL_INFO      # genuinely cells
