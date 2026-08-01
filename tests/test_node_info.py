"""Tests for NODE_INFO (reg 21000) sub-device enumeration — real AP300 data."""

import pathlib

from custom_components.bluetti_cloud.api.modbus import (
    NODE_INFO,
    build_node_info_query,
    node_is_battery,
    node_model_name,
    parse_node_info,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex300"


def test_node_query_is_v2_fc16_write_to_21000():
    # Query-write: V2 envelope for reg 21000 + FC=16 write of the version selector.
    payload = build_node_info_query(version=1, payload_ver=1.2)
    assert payload[:10] == bytes.fromhex("01f80f52080000000000")  # 21000 = 0x5208
    # Modbus FC=16 write: slave 0, fc 0x10, reg 0x5208, qty 1, bytecount 2, val 0x0001
    assert payload[10:19] == bytes.fromhex("001052080001020001")


def test_parse_node_info_real_ap300():
    data = bytes.fromhex((FIXTURES / "node_info_v1.hex").read_text().strip())
    nodes = parse_node_info(data)
    assert len(nodes) == 3

    inv, hub, bat = nodes
    assert inv["slave_addr"] == 0
    assert inv["model"] == 6
    assert inv["online"] is True

    assert hub["slave_addr"] == 11
    assert hub["model"] == 3007
    assert node_model_name(hub["model"]) == "D1 Hub (HD1)"
    assert node_is_battery(hub["model"]) is False

    assert bat["slave_addr"] == 51
    assert bat["model"] == 4005
    assert node_is_battery(bat["model"]) is True
    assert node_model_name(bat["model"]) == "B300"
    assert bat["online"] is True


def test_node_model_names():
    assert node_model_name(6) == "AP300"
    assert node_model_name(3008) == "A1 Hub (HA1)"


def test_battery_models_are_named_specifically():
    # Battery pack codes come from the app's PackModel table.
    assert node_model_name(4005) == "B300"
    assert node_model_name(4006) == "B300K"
    assert node_model_name(4016) == "B500K"
    assert node_model_name(4000) == "B500"
    assert node_model_name(4014) == "B230"
    # Unknown battery codes still identify as a battery
    assert node_is_battery(4099) is True
    assert node_model_name(4099) == "Battery (4099)"


def test_real_ap300_external_battery_is_b300():
    data = bytes.fromhex((FIXTURES / "node_info_v1.hex").read_text().strip())
    battery = next(n for n in parse_node_info(data) if n["is_battery"])
    assert battery["model"] == 4005
    assert battery["model_name"] == "B300"


def test_node_info_reg_constant():
    assert NODE_INFO == 21000
