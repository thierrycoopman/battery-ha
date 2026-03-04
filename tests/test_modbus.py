"""Tests for Modbus RTU frame builder, parser, and homeData register map."""

import struct

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    AC_SWITCH,
    DC_SWITCH,
    EXCEPTION_ILLEGAL_DATA_ADDRESS,
    EXCEPTION_ILLEGAL_FUNCTION,
    FUNC_ERROR_MASK,
    FUNC_READ_HOLDING,
    FUNC_WRITE_MULTIPLE,
    FUNC_WRITE_SINGLE,
    HOME_DATA,
    HOME_DATA_COUNT,
    PACK_ITEM_INFO,
    PACK_ITEM_INFO_COUNT,
    PACK_MAIN_INFO,
    PACK_MAIN_INFO_COUNT,
    SWITCH_OFF,
    SWITCH_ON,
    build_mqtt_payload,
    build_read_command,
    build_read_mqtt_payload,
    build_write_command,
    crc16_modbus,
    parse_home_data,
    parse_mqtt_payload,
    parse_pack_item_info,
    parse_pack_main_info,
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


# -- Build write commands --

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


# -- Build read commands --

def test_build_read_command_structure():
    """FC=03 read command should have correct structure."""
    cmd = build_read_command(HOME_DATA, HOME_DATA_COUNT)
    assert len(cmd) == 8  # slave(1) + FC(1) + reg(2) + count(2) + CRC(2)
    assert cmd[0] == 1  # slave addr
    assert cmd[1] == 0x03  # FC=03
    # Register 100 = 0x0064
    assert cmd[2] == 0x00
    assert cmd[3] == 0x64
    # Count 62 = 0x003E
    assert cmd[4] == 0x00
    assert cmd[5] == 0x3E


def test_build_read_command_crc_valid():
    """Read command CRC should verify correctly."""
    cmd = build_read_command(HOME_DATA, HOME_DATA_COUNT)
    expected_crc = crc16_modbus(cmd[:-2])
    assert cmd[-2:] == expected_crc


def test_build_read_command_custom_slave():
    """Read command with custom slave address."""
    cmd = build_read_command(PACK_ITEM_INFO, PACK_ITEM_INFO_COUNT, slave_addr=2)
    assert cmd[0] == 2  # slave addr = 2
    assert cmd[1] == 0x03


def test_build_read_command_pack_main_info():
    """Read command for PackMainInfo register 6000."""
    cmd = build_read_command(PACK_MAIN_INFO, PACK_MAIN_INFO_COUNT)
    # Register 6000 = 0x1770
    assert cmd[2] == 0x17
    assert cmd[3] == 0x70
    # Count 34 = 0x0022
    assert cmd[4] == 0x00
    assert cmd[5] == 0x22


def test_build_read_mqtt_payload_adds_protocol_byte():
    """Read MQTT payload should have 0x01 prefix."""
    payload = build_read_mqtt_payload(HOME_DATA, HOME_DATA_COUNT)
    assert payload[0] == 0x01
    assert len(payload) == 9  # 1 proto + 8 modbus


def test_build_read_mqtt_payload_parses_as_valid():
    """Build read payload and verify it parses as valid Modbus."""
    payload = build_read_mqtt_payload(PACK_MAIN_INFO, PACK_MAIN_INFO_COUNT)
    # The payload is a request frame (FC=03 with reg+count), not a response
    # parse_mqtt_payload handles FC=03 responses, but the structure is similar
    # Let's verify the raw frame is valid CRC
    frame = payload[1:]  # strip protocol byte
    assert crc16_modbus(frame[:-2]) == frame[-2:]


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


# -- FC=0x83 error response parsing --

def test_parse_mqtt_payload_fc83_error():
    """Parse a Modbus error response (FC=0x83 = error for FC=0x03)."""
    # [slave=1] [FC=0x83] [exception=0x02] [CRC]
    frame = bytearray([0x01, 0x83, 0x02])
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)

    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["is_error"] is True
    assert result["original_fc"] == FUNC_READ_HOLDING
    assert result["exception_code"] == EXCEPTION_ILLEGAL_DATA_ADDRESS


def test_parse_mqtt_payload_fc86_error():
    """Parse a Modbus error response for FC=0x06 write."""
    frame = bytearray([0x01, 0x86, 0x01])  # Illegal function
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)

    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["is_error"] is True
    assert result["original_fc"] == FUNC_WRITE_SINGLE
    assert result["exception_code"] == EXCEPTION_ILLEGAL_FUNCTION


# -- FC=0x10 write multiple registers (device data push) --

def test_parse_mqtt_payload_fc10_data_push():
    """Parse a FC=16 data push from device with start_addr and register data."""
    register_data = bytearray(20)
    struct.pack_into(">H", register_data, 0, 532)  # Some value
    # Body: [start_addr(2)] [quantity(2)] [byte_count(1)] [data(N)]
    body = bytearray()
    body += struct.pack(">H", HOME_DATA)  # start_addr = 100
    body += struct.pack(">H", 10)  # quantity = 10 registers
    body.append(len(register_data))  # byte_count
    body += register_data
    frame = bytearray([0x01, FUNC_WRITE_MULTIPLE]) + body
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)

    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["function_code"] == FUNC_WRITE_MULTIPLE
    assert result["start_addr"] == HOME_DATA
    assert result["quantity"] == 10
    assert result["byte_count"] == 20
    assert len(result["register_data"]) == 20
    assert "is_error" not in result


def test_parse_mqtt_payload_fc10_pack_main_info():
    """Parse a FC=16 push for PackMainInfo register range."""
    register_data = bytearray(68)
    body = bytearray()
    body += struct.pack(">H", PACK_MAIN_INFO)  # start_addr = 6000
    body += struct.pack(">H", 34)  # quantity
    body.append(len(register_data))
    body += register_data
    frame = bytearray([0x01, FUNC_WRITE_MULTIPLE]) + body
    frame += crc16_modbus(bytes(frame))
    payload = bytes([0x01]) + bytes(frame)

    result = parse_mqtt_payload(payload)
    assert result is not None
    assert result["start_addr"] == PACK_MAIN_INFO
    assert result["quantity"] == 34


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


# -- PackMainInfo parser (register 6000) --

def _build_pack_main_info(
    pack_count=2, total_voltage=532, total_current=-15,
    total_soc=87, total_soh=95, avg_temp=65,
    charging_status=1, charge_full=120, discharge_empty=45,
    size=68,
):
    """Helper to build PackMainInfo bytes with specific values."""
    data = bytearray(size)
    # pack_volt_type at 0-1
    struct.pack_into(">H", data, 0, 1)
    # pack_count at byte 3
    data[3] = pack_count
    # pack_online_mask at 4-5 (both packs online)
    struct.pack_into(">H", data, 4, (1 << pack_count) - 1)
    # total_voltage at 6-7
    struct.pack_into(">H", data, 6, total_voltage)
    # total_current at 8-9
    struct.pack_into(">h", data, 8, total_current)
    # total_soc at byte 11
    data[11] = total_soc
    # total_soh at byte 13
    data[13] = total_soh
    # average_temp at 14-15 (value + 40 offset)
    struct.pack_into(">H", data, 14, avg_temp)
    # running_status at byte 17
    data[17] = 1
    # charging_status at byte 19
    data[19] = charging_status
    # charge_full_time at 34-35
    struct.pack_into(">H", data, 34, charge_full)
    # discharge_empty_time at 36-37
    struct.pack_into(">H", data, 36, discharge_empty)
    return bytes(data)


def test_parse_pack_main_info_basic():
    """Parse basic PackMainInfo fields."""
    data = _build_pack_main_info(
        pack_count=2, total_voltage=532, total_current=-15,
        total_soc=87, total_soh=95, avg_temp=65,
    )
    result = parse_pack_main_info(data)

    assert result["pack_count"] == 2
    assert result["pack_total_voltage"] == 53.2
    assert result["pack_total_current"] == -1.5
    assert result["pack_total_soc"] == 87
    assert result["pack_total_soh"] == 95
    assert result["pack_average_temp"] == 25  # 65 - 40 = 25°C


def test_parse_pack_main_info_charging_status():
    """Test charging status mapping."""
    data = _build_pack_main_info(charging_status=2)
    result = parse_pack_main_info(data)
    assert result["pack_charging_status_text"] == "discharging"


def test_parse_pack_main_info_charge_times():
    """Test charge/discharge time fields."""
    data = _build_pack_main_info(charge_full=180, discharge_empty=90)
    result = parse_pack_main_info(data)
    assert result["charge_full_time"] == 180
    assert result["discharge_empty_time"] == 90


def test_parse_pack_main_info_too_short():
    """Short data should return empty dict."""
    assert parse_pack_main_info(b"") == {}
    assert parse_pack_main_info(b"\x00" * 10) == {}


def test_parse_pack_main_info_online_mask():
    """Pack online mask should reflect online packs."""
    data = _build_pack_main_info(pack_count=2)
    result = parse_pack_main_info(data)
    assert result["pack_online_mask"] == 0b11  # Both packs online


def test_parse_pack_main_info_zero_temp():
    """Temperature of exactly 40 raw = 0°C after offset."""
    data = _build_pack_main_info(avg_temp=40)
    result = parse_pack_main_info(data)
    assert result["pack_average_temp"] == 0


# -- PackItemInfo parser (register 6100) --

def _build_pack_item_info(
    pack_id=1, voltage=5320, current=-15,
    soc=87, soh=95, avg_temp=65,
    charging_status=1,
    size=52,
):
    """Helper to build PackItemInfo bytes with specific values."""
    data = bytearray(size)
    # pack_id at byte 1
    data[1] = pack_id
    # pack_type ASCII at 2-13
    pack_type = b"B2-PLUS     "
    data[2:14] = pack_type[:12]
    # pack_sn ASCII at 14-21
    pack_sn = b"SN123456"
    data[14:22] = pack_sn[:8]
    # voltage at 22-23 (u16 / 100.0)
    struct.pack_into(">H", data, 22, voltage)
    # current at 24-25 (s16 / 10.0)
    struct.pack_into(">h", data, 24, current)
    # soc at byte 27
    data[27] = soc
    # soh at byte 29
    data[29] = soh
    # average_temp at 30-31 (value + 40 offset)
    struct.pack_into(">H", data, 30, avg_temp)
    # running_status at byte 49
    data[49] = 1
    # charging_status at byte 51
    data[51] = charging_status
    return bytes(data)


def test_parse_pack_item_info_basic():
    """Parse basic PackItemInfo fields."""
    data = _build_pack_item_info(
        pack_id=1, voltage=5320, current=-15,
        soc=87, soh=95, avg_temp=65,
    )
    result = parse_pack_item_info(data)

    assert result["pack_id"] == 1
    assert result["pack_voltage"] == 53.20
    assert result["pack_current"] == -1.5
    assert result["pack_soc"] == 87
    assert result["pack_soh"] == 95
    assert result["pack_average_temp"] == 25  # 65 - 40


def test_parse_pack_item_info_pack_type_and_sn():
    """Test pack type and serial number parsing."""
    data = _build_pack_item_info()
    result = parse_pack_item_info(data)
    assert result["pack_type"] == "B2-PLUS"
    assert result["pack_sn"] == "SN123456"


def test_parse_pack_item_info_charging_status():
    """Test charging status in pack item."""
    data = _build_pack_item_info(charging_status=2)
    result = parse_pack_item_info(data)
    assert result["pack_charging_status_text"] == "discharging"


def test_parse_pack_item_info_pack2():
    """Test parsing pack 2 data."""
    data = _build_pack_item_info(pack_id=2, soc=72, soh=90)
    result = parse_pack_item_info(data)
    assert result["pack_id"] == 2
    assert result["pack_soc"] == 72
    assert result["pack_soh"] == 90


def test_parse_pack_item_info_positive_current():
    """Positive current indicates pack charging."""
    data = _build_pack_item_info(current=250)  # 25.0A
    result = parse_pack_item_info(data)
    assert result["pack_current"] == 25.0


def test_parse_pack_item_info_too_short():
    """Short data should return empty dict."""
    assert parse_pack_item_info(b"") == {}
    assert parse_pack_item_info(b"\x00" * 10) == {}


def test_parse_pack_item_info_minimal():
    """Data with just enough bytes for core fields."""
    data = bytearray(26)
    data[1] = 3  # pack_id
    struct.pack_into(">H", data, 22, 4800)  # voltage
    struct.pack_into(">h", data, 24, 50)  # current
    result = parse_pack_item_info(bytes(data))
    assert result["pack_id"] == 3
    assert result["pack_voltage"] == 48.0
    assert result["pack_current"] == 5.0
    # Optional fields not present
    assert "pack_soc" not in result
    assert "pack_soh" not in result
