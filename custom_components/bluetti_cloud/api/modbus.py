"""Modbus RTU frame builder, parser, and CRC16 for Bluetti device control.

The Bluetti IoT protocol uses standard Modbus RTU frames to communicate
with devices. Outbound commands use function code 0x06 (write single register).
Inbound telemetry uses function code 0x03 (read holding registers response).

MQTT payloads are prefixed with a protocol byte (0x01 = MODBUS_RTU).
"""

from __future__ import annotations

import logging
import struct
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Modbus register addresses for AC300 (ProtocolAddr, protocolVer < 2020)
AC_SWITCH = 3007  # 0x0BBF — ProtocolAddr.AC_SWITCH
DC_SWITCH = 3008  # 0x0BC0 — ProtocolAddr.DC_SWITCH

# Switch command values: simple 0/1 for AC300
SWITCH_ON = 1
SWITCH_OFF = 0

# Modbus function codes
FUNC_READ_HOLDING = 0x03
FUNC_WRITE_SINGLE = 0x06

# Default slave address (0 for 2nd gen IoT, 1 for older)
DEFAULT_SLAVE_ADDR = 1


def crc16_modbus(data: bytes) -> bytes:
    """Calculate Modbus CRC16 checksum.

    Standard CRC16 with polynomial 0xA001, returns bytes in
    low-byte-first order as required by Modbus RTU.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    # Return low byte first (Modbus byte order)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_write_command(
    register: int,
    value: int,
    slave_addr: int = DEFAULT_SLAVE_ADDR,
) -> bytes:
    """Build a Modbus RTU single-register write command.

    Frame format: [slave(1)] [0x06(1)] [register(2)] [value(2)] [CRC(2)]

    Args:
        register: Register address (e.g., AC_SWITCH=3007).
        value: Value to write (e.g., SWITCH_ON=1, SWITCH_OFF=0).
        slave_addr: Modbus slave address (default 1).

    Returns:
        Complete Modbus RTU frame as bytes.
    """
    frame = bytes([
        slave_addr,
        FUNC_WRITE_SINGLE,
        (register >> 8) & 0xFF,
        register & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_mqtt_payload(register: int, value: int, slave_addr: int = DEFAULT_SLAVE_ADDR) -> bytes:
    """Build the full MQTT payload for a device command.

    The MQTT payload is: protocol_type_byte + modbus_frame
    Protocol type 0x01 = MODBUS_RTU.

    Args:
        register: Register address.
        value: Value to write.
        slave_addr: Modbus slave address.

    Returns:
        Complete MQTT payload bytes.
    """
    modbus_frame = build_write_command(register, value, slave_addr)
    # Prefix with protocol type byte: 0x01 = MODBUS_RTU
    return bytes([0x01]) + modbus_frame


# ---------------------------------------------------------------------------
# Modbus frame PARSER (inbound telemetry + write echoes)
# ---------------------------------------------------------------------------

PROTOCOL_BYTE = 0x01  # MODBUS_RTU


def _verify_crc(frame: bytes) -> bool:
    """Verify CRC16 of a Modbus RTU frame (last 2 bytes are CRC)."""
    if len(frame) < 4:
        return False
    expected = crc16_modbus(frame[:-2])
    return frame[-2:] == expected


def parse_mqtt_payload(payload: bytes) -> dict[str, Any] | None:
    """Parse an MQTT payload containing a Modbus RTU frame.

    Returns dict with keys:
        slave_addr, function_code, data (bytes)
        For FC=06: also register_addr, value
        For FC=03: also byte_count, register_data (bytes)
    Returns None if frame is invalid or CRC fails.
    """
    if not payload or len(payload) < 6:
        return None

    # Strip protocol byte
    if payload[0] == PROTOCOL_BYTE:
        frame = payload[1:]
    else:
        frame = payload

    if not _verify_crc(frame):
        _LOGGER.debug("Modbus CRC failed: %s", payload.hex())
        return None

    slave_addr = frame[0]
    fc = frame[1]
    # Strip CRC from data
    body = frame[2:-2]

    result: dict[str, Any] = {
        "slave_addr": slave_addr,
        "function_code": fc,
    }

    if fc == FUNC_READ_HOLDING and len(body) >= 1:
        # FC=03 response: [byte_count(1)] [register_data(N)]
        byte_count = body[0]
        register_data = body[1 : 1 + byte_count]
        result["byte_count"] = byte_count
        result["register_data"] = register_data
        result["data"] = register_data
    elif fc == FUNC_WRITE_SINGLE and len(body) >= 4:
        # FC=06 echo: [register(2)] [value(2)]
        reg_addr = (body[0] << 8) | body[1]
        value = (body[2] << 8) | body[3]
        result["register_addr"] = reg_addr
        result["value"] = value
        result["data"] = body
    else:
        result["data"] = body

    return result


def parse_write_response(payload: bytes) -> tuple[int, int] | None:
    """Parse an FC=06 write echo from MQTT payload.

    Returns (register_addr, value) or None if not a valid write echo.
    """
    parsed = parse_mqtt_payload(payload)
    if not parsed or parsed["function_code"] != FUNC_WRITE_SINGLE:
        return None
    if "register_addr" not in parsed:
        return None
    return (parsed["register_addr"], parsed["value"])


# ---------------------------------------------------------------------------
# HomeData register map — from ProtocolParserV2.java:parseHomeData()
# ---------------------------------------------------------------------------
# Byte indices into the FC=03 register data for homeData frames.
# Basic fields are available on all protocolVer.
# Extended fields require protocolVer >= 2001.


def _u16(data: bytes, offset: int) -> int:
    """Read unsigned 16-bit big-endian value at offset."""
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from(">H", data, offset)[0]


def _s16(data: bytes, offset: int) -> int:
    """Read signed 16-bit big-endian value at offset."""
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from(">h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    """Read unsigned 32-bit big-endian value at offset."""
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from(">I", data, offset)[0]


def _s32(data: bytes, offset: int) -> int:
    """Read signed 32-bit big-endian value at offset."""
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from(">i", data, offset)[0]


def _ascii(data: bytes, offset: int, length: int) -> str:
    """Read ASCII string at offset, stripping nulls."""
    if offset + length > len(data):
        return ""
    return data[offset : offset + length].decode("ascii", errors="ignore").strip("\x00 ")


# Charging status codes from ProtocolParserV2
CHARGING_STATUS_MAP = {
    0: "standby",
    1: "charging",
    2: "discharging",
    3: "standby",  # idle
    4: "charging",  # AC charging
    5: "charging",  # solar charging
}

# Ctrl status bit flags (byte indices 48-49)
CTRL_STATUS_BITS = {
    0: "ac_switch",
    1: "dc_switch",
    2: "pv_switch",
    3: "grid_switch",
    4: "eco_mode",
    5: "ups_mode",
    6: "bypass_auto",
    7: "led_switch",
    8: "heating_switch",
    9: "buzzer_switch",
    10: "smart_sleep",
}


def parse_home_data(data: bytes) -> dict[str, Any]:
    """Parse homeData register values into named fields.

    Works for both basic (protocolVer < 2001) and extended frames.
    The data parameter is the register_data from an FC=03 response.
    """
    result: dict[str, Any] = {}

    if len(data) < 12:
        return result

    # Basic fields (all protocolVer, byte indices)
    result["pack_voltage"] = _u16(data, 0) / 10.0
    result["pack_current"] = _s16(data, 2) / 10.0
    result["battery_soc"] = _u16(data, 4)
    raw_charging = _u16(data, 6)
    result["charging_status_raw"] = raw_charging
    result["charging_status"] = CHARGING_STATUS_MAP.get(raw_charging, f"unknown({raw_charging})")
    result["charge_time_remaining"] = _u16(data, 8)
    result["discharge_time_remaining"] = _u16(data, 10)

    if len(data) > 13:
        result["pack_aging_info"] = _u16(data, 12)

    if len(data) > 15:
        result["pack_count"] = min(_u16(data, 14) & 0xFF, 16)

    if len(data) > 17:
        result["pack_online_mask"] = _u16(data, 16)

    if len(data) > 31:
        result["device_model"] = _ascii(data, 20, 12)

    if len(data) > 39:
        result["device_sn"] = _ascii(data, 32, 8)

    if len(data) > 41:
        result["inverter_count"] = data[41]

    if len(data) > 45:
        result["inverter_power_type"] = data[45]

    if len(data) > 47:
        result["energy_flow"] = _u16(data, 46)

    # Ctrl status flags (bytes 48-49) — switch states from device
    if len(data) > 49:
        ctrl = _u16(data, 48)
        for bit, name in CTRL_STATUS_BITS.items():
            result[f"ctrl_{name}"] = bool(ctrl & (1 << bit))

    # Extended fields (protocolVer >= 2001, byte indices 80+)
    if len(data) > 99:
        result["total_dc_power"] = _u32(data, 80)
        result["total_ac_power"] = _u32(data, 84)
        result["total_pv_power"] = _u32(data, 88)
        result["total_grid_power"] = _s32(data, 92)
        result["total_inv_power"] = _u32(data, 96)

    if len(data) > 119:
        result["total_dc_energy"] = _u32(data, 100) / 10.0
        result["total_ac_energy"] = _u32(data, 104) / 10.0
        result["total_pv_energy"] = _u32(data, 108) / 10.0
        result["total_grid_energy"] = _u32(data, 112) / 10.0
        result["total_feedback_energy"] = _u32(data, 116) / 10.0

    if len(data) > 121:
        result["charging_mode"] = data[121]

    if len(data) > 123:
        result["inv_working_status"] = data[123]

    return result
