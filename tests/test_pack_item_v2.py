"""Tests for the V2 per-pack record parser (reg 6100), real AP300 payload."""

import pathlib

from custom_components.bluetti_cloud.api.modbus import parse_pack_item_info_v2

# Real capture from the AP300 main unit (Modbus data portion of a reg-6100 read).
REAL = bytes.fromhex(
    (pathlib.Path(__file__).parent / "fixtures" / "apex300" / "pack_item_v2.hex")
    .read_text()
    .strip()
)


def test_parse_v2_pack_item_real_payload():
    p = parse_pack_item_info_v2(REAL)
    assert p["pack_id"] == 0
    # ASCII model is byte-swapped per register: raw "PA03" -> "AP300"
    assert p["pack_type"] == "AP300"
    # SN registers are reversed then rendered as decimal
    assert p["pack_sn"] == "2616113487436"
    assert p["pack_soc"] == 95
    # This record genuinely reports no per-pack electricals (main unit)
    assert p["pack_voltage"] == 0.0
    assert p["total_cell_count"] == 16
    assert p["ntc_cell_count"] == 4


def test_v2_voltage_uses_hundredths():
    # voltage at bytes 22-23, /100 (V2 per-pack convention)
    data = bytearray(60)
    data[22:24] = (5313).to_bytes(2, "big")
    p = parse_pack_item_info_v2(bytes(data))
    assert p["pack_voltage"] == 53.13


def test_v2_temperature_offset_is_minus_40():
    data = bytearray(60)
    data[30:32] = (65).to_bytes(2, "big")
    p = parse_pack_item_info_v2(bytes(data))
    assert p["pack_average_temp"] == 25


def test_v2_zero_temperature_is_none_not_minus_40():
    # The app leaves an unguarded -40 on empty records; we surface None instead.
    p = parse_pack_item_info_v2(bytes(60))
    assert p["pack_average_temp"] is None
