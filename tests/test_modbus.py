"""Tests for Modbus RTU frame builder, parser, and homeData register map."""

import struct

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    AC_SWITCH,
    DC_SWITCH,
    FUNC_READ_HOLDING,
    FUNC_WRITE_SINGLE,
    SWITCH_OFF,
    SWITCH_ON,
    build_mqtt_payload,
    build_write_command,
    crc16_modbus,
    parse_home_data,
    parse_mqtt_payload,
    parse_write_response,
)


# -- CRC16 --

def test_crc16_known_frame():
    """Verify CRC16 for a known Modbus frame."""
    # Frame: slave=1, FC=06, reg=0x0BBF, val=0x0001
    frame = bytes([0x01, 0x06, 0x0B, 0xBF, 0x00, 0x01])
    crc = crc16_modbus(frame)
    assert crc == bytes([0x7B, 0xCA])


def test_crc16_empty():
    """CRC of empty data should be 0xFFFF."""
    crc = crc16_modbus(b"")
    assert crc == bytes([0xFF, 0xFF])


# -- Build commands --

def test_build_write_command_ac_on():
    """Test building AC ON command."""
    cmd = build_write_command(AC_SWITCH, SWITCH_ON)
    assert cmd == bytes.fromhex("01060bbf00017bca")


def test_build_write_command_dc_off():
    """Test building DC OFF command."""
    cmd = build_write_command(DC_SWITCH, SWITCH_OFF)
    assert cmd == bytes.fromhex("01060bc000008bd2")


def test_build_mqtt_payload_adds_protocol_byte():
    """MQTT payload should have 0x01 prefix."""
    payload = build_mqtt_payload(AC_SWITCH, SWITCH_ON)
    assert payload[0] == 0x01
    assert len(payload) == 9  # 1 proto + 8 modbus


def test_build_mqtt_payload_roundtrip():
    """Build and parse back should yield same register/value."""
    payload = build_mqtt_payload(AC_SWITCH, SWITCH_ON)
    assert payload.hex() == "0101060bbf00017bca"
    result = parse_write_response(payload)
    assert result == (AC_SWITCH, SWITCH_ON)


# -- Parse FC=06 write echoes --

def test_parse_write_response_ac_on():
    """Parse known AC ON write echo."""
    payload = bytes.fromhex("0101060bbf00017bca")
    result = parse_write_response(payload)
    assert result == (3007, 1)


def test_parse_write_response_dc_off():
    """Parse DC OFF write echo."""
    payload = build_mqtt_payload(DC_SWITCH, SWITCH_OFF)
    result = parse_write_response(payload)
    assert result == (DC_SWITCH, SWITCH_OFF)


def test_parse_write_response_crc_fail():
    """Corrupted CRC should return None."""
    payload = bytearray(bytes.fromhex("0101060bbf00017bca"))
    payload[-1] ^= 0xFF
    assert parse_write_response(bytes(payload)) is None


def test_parse_write_response_too_short():
    """Too-short payload should return None."""
    assert parse_write_response(b"\x01\x02") is None
    assert parse_write_response(b"") is None


def test_parse_write_response_fc03_returns_none():
    """FC=03 frame should not be parsed as write response."""
    data = bytearray(12)
    frame = bytearray([0x01, 0x03, len(data)]) + data
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)
    assert parse_write_response(payload) is None


# -- Parse FC=03 read responses --

def test_parse_mqtt_payload_fc03():
    """Parse a valid FC=03 response."""
    data = bytearray(20)
    struct.pack_into(">H", data, 0, 532)
    frame = bytearray([0x01, 0x03, len(data)]) + data
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)

    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["function_code"] == FUNC_READ_HOLDING
    assert result["byte_count"] == 20
    assert len(result["register_data"]) == 20


def test_parse_mqtt_payload_fc06():
    """Parse a valid FC=06 response."""
    payload = bytes.fromhex("0101060bbf00017bca")
    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["function_code"] == FUNC_WRITE_SINGLE
    assert result["register_addr"] == 3007
    assert result["value"] == 1


def test_parse_mqtt_payload_with_protocol_byte():
    """Frame with 0x01 protocol prefix should parse correctly."""
    # Build MQTT payload (protocol byte + modbus frame)
    payload = build_mqtt_payload(AC_SWITCH, SWITCH_ON)
    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["register_addr"] == AC_SWITCH
    assert result["value"] == SWITCH_ON


def test_parse_mqtt_payload_none_on_invalid():
    """Invalid data should return None."""
    assert parse_mqtt_payload(b"") is None
    assert parse_mqtt_payload(None) is None
    assert parse_mqtt_payload(b"\x01\x02\x03") is None


# -- HomeData register map --

def _build_home_data(
    voltage=0, current=0, soc=0, charging=0,
    charge_time=0, discharge_time=0, ctrl=0,
    size=60,
):
    """Helper to build homeData bytes with specific values."""
    data = bytearray(size)
    struct.pack_into(">H", data, 0, voltage)
    struct.pack_into(">h", data, 2, current)
    struct.pack_into(">H", data, 4, soc)
    struct.pack_into(">H", data, 6, charging)
    struct.pack_into(">H", data, 8, charge_time)
    struct.pack_into(">H", data, 10, discharge_time)
    struct.pack_into(">H", data, 48, ctrl)
    return bytes(data)


def test_parse_home_data_basic():
    """Parse basic homeData fields."""
    data = _build_home_data(
        voltage=532, current=-15, soc=87,
        charging=2, charge_time=120, discharge_time=45,
    )
    hd = parse_home_data(data)

    assert hd["pack_voltage"] == 53.2
    assert hd["pack_current"] == -1.5
    assert hd["battery_soc"] == 87
    assert hd["charging_status"] == "discharging"
    assert hd["charge_time_remaining"] == 120
    assert hd["discharge_time_remaining"] == 45


def test_parse_home_data_charging_status_codes():
    """Test all known charging status codes."""
    for code, expected in [(0, "standby"), (1, "charging"), (2, "discharging"), (4, "charging"), (5, "charging")]:
        data = _build_home_data(charging=code)
        hd = parse_home_data(data)
        assert hd["charging_status"] == expected, f"Code {code} should be {expected}"


def test_parse_home_data_unknown_charging_status():
    """Unknown charging status code should produce descriptive string."""
    data = _build_home_data(charging=99)
    hd = parse_home_data(data)
    assert "unknown" in hd["charging_status"]


def test_parse_home_data_ctrl_flags():
    """Test ctrl status bit flags."""
    ctrl = 0b00000011  # AC + DC on
    data = _build_home_data(ctrl=ctrl)
    hd = parse_home_data(data)

    assert hd["ctrl_ac_switch"] is True
    assert hd["ctrl_dc_switch"] is True
    assert hd["ctrl_pv_switch"] is False
    assert hd["ctrl_grid_switch"] is False


def test_parse_home_data_all_switches_on():
    """Test with all ctrl switches on."""
    ctrl = 0b11111111111  # All 11 bits on
    data = _build_home_data(ctrl=ctrl)
    hd = parse_home_data(data)

    assert hd["ctrl_ac_switch"] is True
    assert hd["ctrl_dc_switch"] is True
    assert hd["ctrl_eco_mode"] is True
    assert hd["ctrl_buzzer_switch"] is True
    assert hd["ctrl_smart_sleep"] is True


def test_parse_home_data_too_short():
    """Very short data should return minimal or empty dict."""
    assert parse_home_data(b"") == {}
    assert parse_home_data(b"\x00" * 5) == {}


def test_parse_home_data_extended_fields():
    """Test extended fields for protocolVer >= 2001."""
    data = bytearray(124)
    struct.pack_into(">H", data, 0, 532)
    struct.pack_into(">H", data, 4, 72)
    # Extended power fields at byte 80+
    struct.pack_into(">I", data, 80, 1500)  # total_dc_power
    struct.pack_into(">I", data, 84, 1200)  # total_ac_power
    struct.pack_into(">I", data, 88, 2000)  # total_pv_power
    struct.pack_into(">i", data, 92, -500)  # total_grid_power (signed)
    # Energy fields at 100+
    struct.pack_into(">I", data, 100, 35)   # total_dc_energy = 3.5
    struct.pack_into(">I", data, 104, 452)  # total_ac_energy = 45.2

    hd = parse_home_data(bytes(data))

    assert hd["total_dc_power"] == 1500
    assert hd["total_ac_power"] == 1200
    assert hd["total_pv_power"] == 2000
    assert hd["total_grid_power"] == -500
    assert hd["total_dc_energy"] == 3.5
    assert hd["total_ac_energy"] == 45.2


def test_parse_home_data_zero_values():
    """Zero values should be preserved (not confused with None)."""
    data = _build_home_data(voltage=0, current=0, soc=0)
    hd = parse_home_data(data)

    assert hd["pack_voltage"] == 0.0
    assert hd["pack_current"] == 0.0
    assert hd["battery_soc"] == 0


def test_parse_home_data_positive_current():
    """Positive current indicates charging."""
    data = _build_home_data(current=250)  # 25.0A charging
    hd = parse_home_data(data)

    assert hd["pack_current"] == 25.0
