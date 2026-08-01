"""Tests for the protocolVer>=2000 (iotPayloadVer 1.2) MQTT framing.

Uses real payloads captured live from an AP300 (APEX 300).
"""

import pathlib

from custom_components.bluetti_cloud.api.modbus import (
    build_mqtt_payload,
    build_read_mqtt_payload,
    parse_home_data,
    parse_mqtt_payload,
    parse_pack_main_info,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "apex300"


def _load(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / name).read_text().strip())


def test_v2_read_payload_has_envelope_and_slave_zero():
    # protocolVer>=2000 read: 01 F8 0F <reg2> 00*5 + Modbus RTU (slave 0).
    payload = build_read_mqtt_payload(100, 62, slave_addr=0, payload_ver=1.2)
    assert payload[:10] == bytes.fromhex("01f80f00640000000000")
    # Modbus RTU follows: slave 0x00, FC 0x03, reg 0x0064, count 0x003e
    assert payload[10:16] == bytes.fromhex("00030064003e")


def test_v1_read_payload_unchanged():
    # Default (payload_ver 1.0) keeps the legacy 0x01 + Modbus RTU framing.
    payload = build_read_mqtt_payload(100, 62, slave_addr=1)
    assert payload[0] == 0x01
    assert payload[1] == 0x01  # slave addr, not 0xF8


def test_v2_write_payload_has_envelope():
    payload = build_mqtt_payload(2011, 1, slave_addr=0, payload_ver=1.2)
    assert payload[:10] == bytes.fromhex("01f80f07db0000000000")  # 2011 = 0x07db


def test_parse_v2_home_data_frame():
    # Real captured AP300 homeData reply — 01F8 header must be stripped.
    parsed = parse_mqtt_payload(_load("mqtt_home_data_v2.hex"))
    assert parsed is not None
    assert parsed["function_code"] == 0x03
    assert parsed["byte_count"] == 124
    home = parse_home_data(parsed["register_data"])
    assert home["pack_voltage"] == 531.3
    assert home["battery_soc"] == 95
    assert home["charging_status"] == "standby"
    assert home["pack_count"] == 2  # internal + external


def test_parse_v2_pack_main_frame():
    parsed = parse_mqtt_payload(_load("mqtt_pack_main_v2.hex"))
    assert parsed is not None
    assert parsed["function_code"] == 0x03
    pack = parse_pack_main_info(parsed["register_data"])
    assert pack["pack_total_voltage"] == 531.3
    assert pack["pack_total_soc"] == 95


def test_parse_v1_frame_still_works():
    # Legacy 0x01-prefixed FC=03 response must still parse.
    from custom_components.bluetti_cloud.api.modbus import build_read_command

    inner = build_read_command(100, 1, slave_addr=1)  # not a response, but valid CRC frame
    v1 = bytes([0x01]) + inner
    parsed = parse_mqtt_payload(v1)
    assert parsed is not None
    assert parsed["slave_addr"] == 1
