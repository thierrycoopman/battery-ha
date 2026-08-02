"""The main unit's own battery is a pack too.

An APEX 300 answers a pack read at its own slave address with its internal
battery (type "AP300"), separate from an attached expansion such as a B300 at
slave 51 — the two report different states of charge. Treating only the
expansion as a battery hid the internal one.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

PARENT = "AP3002616113487436"


def _manager(nodes):
    coordinator = MagicMock()
    coordinator.data = {PARENT: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    mgr = BluettiMqttManager(coordinator)
    mgr.overlays[PARENT] = {"nodes": nodes}
    return mgr


def _pack_frame(model: str, soc: int) -> bytes:
    """Minimal V2 pack-item payload carrying a model name and SOC."""
    data = bytearray(208)
    raw = model.encode() + b"\x00" * 12
    # ASCII fields are byte-swapped within each register
    for i in range(6):
        data[2 + i * 2] = raw[i * 2 + 1]
        data[3 + i * 2] = raw[i * 2]
    data[27] = soc
    data[105] = 16
    return bytes(data)


def test_main_unit_pack_is_recorded_against_its_own_node():
    nodes = [
        {"slave_addr": 0, "model": 6, "model_name": "AP300",
         "is_battery": False, "online": True},
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]
    mgr = _manager(nodes)
    mgr._process_pack_item_v2(PARENT, _pack_frame("AP300", 93), 0)
    mgr._process_pack_item_v2(PARENT, _pack_frame("B300", 94), 51)

    by_addr = {n["slave_addr"]: n for n in mgr.overlays[PARENT]["nodes"]}
    # The internal battery is now visible, with its own state of charge...
    assert by_addr[0]["pack_soc"] == 93
    assert by_addr[0]["has_battery"] is True
    # ...distinct from the attached expansion.
    assert by_addr[51]["pack_soc"] == 94
    assert by_addr[51]["pack_model"] == "B300"


def test_node_reporting_a_pack_counts_as_a_battery_for_entities():
    nodes = [{"slave_addr": 0, "model": 6, "model_name": "AP300",
              "is_battery": False, "online": True}]
    mgr = _manager(nodes)
    mgr._process_pack_item_v2(PARENT, _pack_frame("AP300", 93), 0)
    node = mgr.overlays[PARENT]["nodes"][0]
    # Not a battery *model*, but it does have a battery worth showing.
    assert node["is_battery"] is False
    assert node["has_battery"] is True


def test_main_unit_pack_reply_is_parsed_as_v2():
    """Routing was limited to expansion slave addresses (>= 41), so the main
    unit's own pack at slave 0 never reached the V2 parser."""
    nodes = [{"slave_addr": 0, "model": 6, "model_name": "AP300",
              "is_battery": False, "online": True}]
    mgr = _manager(nodes)
    mgr._route_register_data(PARENT, 6100, 0, _pack_frame("AP300", 93))
    node = mgr.overlays[PARENT]["nodes"][0]
    assert node.get("has_battery") is True
    assert node.get("pack_soc") == 93


def test_cell_detail_is_attached_to_the_reporting_pack():
    """Cell data must land on the pack that reported it, not a shared bucket."""
    nodes = [
        {"slave_addr": 0, "model": 6, "model_name": "AP300",
         "is_battery": False, "online": True},
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]
    mgr = _manager(nodes)
    cells = bytearray(50)
    cells[1] = 4      # cell count
    cells[3] = 2      # ntc count
    for i, mv in enumerate((3300, 3310, 3305, 3302)):
        cells[4 + 2 * i] = (mv >> 8) & 0xFF
        cells[5 + 2 * i] = mv & 0xFF
    mgr._process_pack_cells_for_node(PARENT, bytes(cells), 51)

    by_addr = {n["slave_addr"]: n for n in mgr.overlays[PARENT]["nodes"]}
    assert by_addr[51]["cell_count"] == 4
    assert by_addr[51]["cell_voltage_delta"] == 0.01
    # The other pack must not inherit it.
    assert "cell_voltage_delta" not in by_addr[0]
