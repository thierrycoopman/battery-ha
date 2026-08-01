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
    assert node_model_name(bat["model"]) == "Battery"
    assert bat["online"] is True


def test_node_model_names():
    assert node_model_name(6) == "AP300"
    assert node_model_name(3008) == "A1 Hub (HA1)"
    assert node_model_name(4018) == "Battery"


def test_node_info_reg_constant():
    assert NODE_INFO == 21000
