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
PACK_SELECT = 3006  # Write to select which battery pack reports in regs 96-99
AC_SWITCH = 3007    # 0x0BBF — ProtocolAddr.AC_SWITCH
DC_SWITCH = 3008    # 0x0BC0 — ProtocolAddr.DC_SWITCH

# V2 (2nd-gen IoT, protocolVer >= 2000) control registers. Values are plain
# 0/1, same as V1 — despite the different register addresses.
AC_SWITCH_V2 = 2011  # 0x07DB — ProtocolAddrV2.AC_SWITCH
DC_SWITCH_V2 = 2012  # 0x07DC — ProtocolAddrV2.DC_SWITCH

# ECO mode: idle-load auto-shutoff. Each output has an on/off flag plus an
# auto-off delay (hours) and a power threshold (W) below which it counts as idle.
DC_ECO_MODE = 2014          # ProtocolAddrV2.CTRL_DC_ECO_MODE, 0/1
DC_ECO_AUTO_OFF_HOURS = 2015
DC_ECO_POWER = 2016
AC_ECO_MODE = 2017          # ProtocolAddrV2.CTRL_AC_ECO_MODE, 0/1
AC_ECO_AUTO_OFF_HOURS = 2018
AC_ECO_POWER = 2019

# Switch command values: simple 0/1 for both V1 and V2
SWITCH_ON = 1
SWITCH_OFF = 0

# FC=03 read register addresses (ProtocolAddrV2.java)
HOME_DATA = 100          # Aggregate SOC, V/I, charging status, switch states
PACK_MAIN_INFO = 6000    # Battery summary: total V/I/SOC/SOH, temp, charge times
PACK_ITEM_INFO = 6100    # Per-battery pack: V, I, SOC, SOH, temp, status
NODE_INFO = 21000        # V2 sub-device (mesh node) registry — see build_node_info_query
INV_BASE_SETTINGS = 2000  # V2 inverter base settings — authoritative AC/DC switch state
INV_BASE_SETTINGS_COUNT = 30  # 60 bytes

# Register counts for FC=03 reads (number of 16-bit registers)
HOME_DATA_COUNT = 62         # 124 bytes
PACK_MAIN_INFO_COUNT = 34    # 68 bytes
PACK_ITEM_INFO_COUNT = 90    # 180 bytes (V1)
PACK_ITEM_INFO_COUNT_V2 = 104  # 208 bytes — the count the app uses for V2

# Modbus function codes
FUNC_READ_HOLDING = 0x03
FUNC_WRITE_SINGLE = 0x06
FUNC_WRITE_MULTIPLE = 0x10
FUNC_ERROR_MASK = 0x80  # Error responses have bit 7 set (e.g., 0x83 = error for 0x03)

# Modbus exception codes (in error responses)
EXCEPTION_ILLEGAL_FUNCTION = 0x01
EXCEPTION_ILLEGAL_DATA_ADDRESS = 0x02
EXCEPTION_ILLEGAL_DATA_VALUE = 0x03

# Default slave address (0 for 2nd gen IoT, 1 for older)
DEFAULT_SLAVE_ADDR = 1


# ---------------------------------------------------------------------------
# Shared payload-encoding conventions
# ---------------------------------------------------------------------------
#
# Bluetti's parsers apply a few house conventions consistently across payloads
# (ported from the app's ProtocolParse/ProtocolParserV2 helpers):
#   - ASCII fields are byte-swapped WITHIN each 16-bit register (lo then hi),
#     so raw "PA03" is really "AP300" and raw "3B00" is "B300".
#   - Serial numbers concatenate registers in REVERSE order, then render the
#     resulting u64 as a decimal string (the numeric tail of the full SN).
#   - 32-bit values are word-swapped: low register first, then high.
# Scaling: per-pack voltage /100, aggregate voltage & currents /10, V2
# temperatures are raw-40 (V1 used -41).


def ascii_swapped(data: bytes) -> str:
    """Decode an ASCII field that is byte-swapped within each register.

    For each 2-byte register the low byte precedes the high byte; NUL padding
    is skipped. Raw `50 41 30 33 00 30` -> "AP300".
    """
    out: list[str] = []
    for i in range(0, len(data) - 1, 2):
        for byte in (data[i + 1], data[i]):
            if byte:
                out.append(chr(byte))
    return "".join(out)


def device_sn_from_registers(data: bytes) -> str:
    """Decode a numeric serial number field (register order reversed).

    Registers are concatenated last-to-first, big-endian within each register,
    and the result is rendered as a decimal string.
    """
    if len(data) < 2:
        return "0"
    chunks = [data[i : i + 2] for i in range(0, len(data) - 1, 2)]
    joined = b"".join(reversed(chunks))
    value = int.from_bytes(joined, "big")
    return str(value) if value else "0"


def u32_word_swapped(data: bytes) -> int:
    """Decode a 32-bit value stored low-register-first (word swapped)."""
    if len(data) < 4:
        return 0
    return (
        (data[2] << 24) | (data[3] << 16) | (data[0] << 8) | data[1]
    )


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


# iotPayloadVer >= 1.1 (2nd-generation IoT, e.g. AP300 / protocolVer >= 2000)
# wraps the Modbus RTU frame in a 10-byte envelope instead of the single 0x01
# protocol byte: 01 F8 0F <register:2> 00 00 00 00 00 + <modbus RTU>.
IOT_PAYLOAD_VER_V2 = 1.1
_V2_ENVELOPE_HEAD = bytes.fromhex("01F80F")
_V2_ENVELOPE_LEN = 10


def _v2_envelope(register: int) -> bytes:
    """Build the 10-byte iotPayloadVer-1.2 envelope header for a register."""
    return (
        _V2_ENVELOPE_HEAD
        + bytes([(register >> 8) & 0xFF, register & 0xFF])
        + bytes(5)
    )


def _wrap_mqtt_payload(
    register: int, modbus_frame: bytes, payload_ver: float
) -> bytes:
    """Wrap a Modbus RTU frame in the MQTT payload envelope for a payload version."""
    if payload_ver >= IOT_PAYLOAD_VER_V2:
        return _v2_envelope(register) + modbus_frame
    # Legacy iotPayloadVer 1.0: single 0x01 = MODBUS_RTU protocol byte.
    return bytes([0x01]) + modbus_frame


def build_mqtt_payload(
    register: int,
    value: int,
    slave_addr: int = DEFAULT_SLAVE_ADDR,
    payload_ver: float = 1.0,
) -> bytes:
    """Build the full MQTT payload for a device command (write).

    For iotPayloadVer 1.0 the payload is `0x01 + modbus_frame`. For >= 1.1 it is
    the 10-byte `01 F8 0F <reg> 00*5` envelope + modbus_frame.
    """
    modbus_frame = build_write_command(register, value, slave_addr)
    return _wrap_mqtt_payload(register, modbus_frame, payload_ver)


# ---------------------------------------------------------------------------
# Output control (guarded)
# ---------------------------------------------------------------------------
#
# Writes are restricted to this allowlist. Neighbouring registers are
# destructive — on V2 devices 2013 is SYSTEM_POWER_OFF (directly next to the DC
# switch at 2012), 2206 is a factory reset and 2233 starts a battery-aging
# routine — so an off-by-one here would shut down or reset a user's hardware.
CONTROL_REGISTERS = frozenset({
    AC_SWITCH,       # 3007, V1
    DC_SWITCH,       # 3008, V1
    AC_SWITCH_V2,    # 2011, V2
    DC_SWITCH_V2,    # 2012, V2
    DC_ECO_MODE,     # 2014, V2
    AC_ECO_MODE,     # 2017, V2
})

# Numeric settings: register -> (min, max), taken from the ranges the app
# enforces. Values outside these are refused rather than sent.
SETTING_RANGES: dict[int, tuple[int, int]] = {
    DC_ECO_AUTO_OFF_HOURS: (1, 4),
    DC_ECO_POWER: (5, 20),
    AC_ECO_AUTO_OFF_HOURS: (1, 4),
    AC_ECO_POWER: (10, 40),
}


def build_setting_payload(
    register: int,
    value: int,
    slave_addr: int,
    payload_ver: float,
) -> bytes:
    """Build an MQTT payload for a numeric setting write (FC=06).

    Only registers in SETTING_RANGES may be written, and only within their
    documented range.

    Raises:
        ValueError: for an unknown register or an out-of-range value.
    """
    bounds = SETTING_RANGES.get(register)
    if bounds is None:
        raise ValueError(
            f"register {register} is not a settable register — refusing to write"
        )
    low, high = bounds
    if not low <= value <= high:
        raise ValueError(
            f"value {value} out of range for register {register} ({low}-{high})"
        )
    return build_mqtt_payload(register, value, slave_addr, payload_ver)


def build_switch_payload(
    register: int,
    value: int,
    slave_addr: int,
    payload_ver: float,
) -> bytes:
    """Build an MQTT payload for an output-control write (FC=06).

    Only registers in CONTROL_REGISTERS may be written, and only with 0 or 1.

    Raises:
        ValueError: if the register is not a known control register, or the
            value is not 0/1.
    """
    if register not in CONTROL_REGISTERS:
        raise ValueError(
            f"register {register} is not a control register — refusing to write"
        )
    if value not in (SWITCH_OFF, SWITCH_ON):
        raise ValueError(f"invalid switch value {value}: expected 0 or 1")
    return build_mqtt_payload(register, value, slave_addr, payload_ver)


def build_read_command(
    register: int,
    count: int,
    slave_addr: int = DEFAULT_SLAVE_ADDR,
) -> bytes:
    """Build a Modbus RTU read holding registers command (FC=03).

    Frame format: [slave(1)] [0x03(1)] [register(2)] [count(2)] [CRC(2)]

    Args:
        register: Starting register address (e.g., HOME_DATA=100).
        count: Number of 16-bit registers to read.
        slave_addr: Modbus slave address (default 1).

    Returns:
        Complete Modbus RTU frame as bytes.
    """
    frame = bytes([
        slave_addr,
        FUNC_READ_HOLDING,
        (register >> 8) & 0xFF,
        register & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF,
    ])
    return frame + crc16_modbus(frame)


def build_read_mqtt_payload(
    register: int,
    count: int,
    slave_addr: int = DEFAULT_SLAVE_ADDR,
    payload_ver: float = 1.0,
) -> bytes:
    """Build the full MQTT payload for a register read request (FC=03).

    For iotPayloadVer 1.0 the payload is `0x01 + modbus_frame`. For >= 1.1 it is
    the 10-byte `01 F8 0F <reg> 00*5` envelope + modbus_frame.
    """
    modbus_frame = build_read_command(register, count, slave_addr)
    return _wrap_mqtt_payload(register, modbus_frame, payload_ver)


# ---------------------------------------------------------------------------
# NODE_INFO (reg 21000) — V2 sub-device (mesh node) enumeration
# ---------------------------------------------------------------------------
#
# Unlike telemetry reads, NODE_INFO is a write-then-reply query: the app WRITES
# a `version` selector into reg 21000 (FC=16) and the device replies with a
# FC=0x10 frame carrying the list. version=1 = mesh node list (batteries +
# hubs/inverter). Each record is 16 bytes after a 4-byte header.

# Known node model codes (DeviceModel.getFromNumber); batteries are 4000-4999.
NODE_MODEL_NAMES = {
    6: "AP300",
    8: "Elite 200 V2",
    56: "AP500",
    3007: "D1 Hub (HD1)",
    3008: "A1 Hub (HA1)",
    3009: "SolarX 4K",
    3012: "Edock",
}

# Battery pack model codes (PackModel.java) — identifies the specific pack
# model, e.g. B300 vs B300K vs B500K.
BATTERY_MODEL_NAMES = {
    4000: "B500",
    4001: "HV800",
    4002: "ENP500",
    4003: "B1210",
    4004: "B4810",
    4005: "B300",
    4006: "B300K",
    4007: "B300S",
    4008: "B1232",
    4009: "Lead Acid",
    4010: "LFP",
    4012: "B500A",
    4013: "BC200",
    4014: "B230",
    4015: "B210",
    4016: "B500K",
    4017: "B900",
    4018: "HB500",
    4019: "BC260",
    4020: "IB900",
    4021: "IB800",
}


def node_is_battery(model: int) -> bool:
    """True if a node model code is a battery (4000-4999 band)."""
    return 4000 <= model < 5000


def node_model_name(model: int) -> str:
    """Human-readable name for a node model code.

    Batteries resolve to their specific pack model (B300, B300K, B500K, ...);
    unknown battery codes fall back to a generic label with the raw code.
    """
    if node_is_battery(model):
        return BATTERY_MODEL_NAMES.get(model, f"Battery ({model})")
    return NODE_MODEL_NAMES.get(model, f"Unknown({model})")


def build_node_info_query(version: int = 1, payload_ver: float = 1.2) -> bytes:
    """Build the NODE_INFO query payload: FC=16 write of `version` to reg 21000.

    version=1 selects the mesh node list (batteries + hubs/inverter). The device
    replies with a FC=0x10 frame whose register_data is parsed by parse_node_info.
    """
    slave = 0
    frame = bytes([
        slave,
        FUNC_WRITE_MULTIPLE,
        (NODE_INFO >> 8) & 0xFF,
        NODE_INFO & 0xFF,
        0x00, 0x01,          # quantity: 1 register
        0x02,                # byte count
        (version >> 8) & 0xFF, version & 0xFF,
    ])
    frame += crc16_modbus(frame)
    return _wrap_mqtt_payload(NODE_INFO, frame, payload_ver)


def parse_node_info(register_data: bytes) -> list[dict[str, Any]]:
    """Parse a NODE_INFO (version 1) reply into a list of sub-device nodes.

    Layout: 4-byte header ([0:2]=version, [3]=numberOffset) then 16 bytes/node:
        [0]groupNo [1]slaveAddress [2]slaveAddressGroup [3]parentNo
        [4:6]status-bits [6:14]sn [14:16]modelNumber
    status bits: 0=meshOnline 1=upgrade 2=warning 3=error 4=dcEnable.
    """
    if len(register_data) < 4 + 16:
        return []

    body = register_data[4:]
    nodes: list[dict[str, Any]] = []
    for i in range(len(body) // 16):
        r = body[i * 16 : (i + 1) * 16]
        status = (r[4] << 8) | r[5]
        model = (r[14] << 8) | r[15]
        nodes.append({
            "slave_addr": r[1],
            "parent_no": r[3],
            "model": model,
            "model_name": node_model_name(model),
            "is_battery": node_is_battery(model),
            "online": bool(status & 0x01),
            "upgrading": bool(status & 0x02),
            "warning": bool(status & 0x04),
            "error": bool(status & 0x08),
            "sn": r[6:14].hex(),
        })
    return nodes


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

    # Strip the payload envelope to get the raw Modbus RTU frame.
    if len(payload) >= 2 and payload[0] == PROTOCOL_BYTE and payload[1] == 0xF8:
        # iotPayloadVer 1.2 (2nd-gen IoT, e.g. AP300): 10-byte 01 F8 ... header.
        frame = payload[_V2_ENVELOPE_LEN:]
    elif payload[0] == PROTOCOL_BYTE:
        # Legacy iotPayloadVer 1.0: single 0x01 protocol byte.
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

    if fc & FUNC_ERROR_MASK:
        # Error response: [exception_code(1)]
        # FC=0x83 = error for FC=0x03, FC=0x86 = error for FC=0x06, etc.
        result["is_error"] = True
        result["original_fc"] = fc & ~FUNC_ERROR_MASK
        result["exception_code"] = body[0] if body else 0
        result["data"] = body
    elif fc == FUNC_READ_HOLDING and len(body) >= 1:
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
    elif fc == FUNC_WRITE_MULTIPLE and len(body) >= 5:
        # FC=10 data push from device (non-standard Modbus usage by Bluetti):
        # [start_addr(2)] [quantity(2)] [byte_count(1)] [register_data(N)]
        # The device "writes" its state using the FC=16 request format.
        start_addr = (body[0] << 8) | body[1]
        quantity = (body[2] << 8) | body[3]
        byte_count = body[4]
        register_data = body[5 : 5 + byte_count]
        result["start_addr"] = start_addr
        result["quantity"] = quantity
        result["byte_count"] = byte_count
        result["register_data"] = register_data
        result["data"] = register_data
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


# ---------------------------------------------------------------------------
# AC300 FC=16 register parser — from warhammerkid/bluetti_mqtt project
# ---------------------------------------------------------------------------
# Bluetti devices push telemetry via FC=16 (Write Multiple Registers) where
# start_addr = actual Modbus holding register address. This register map was
# reverse-engineered from Bluetooth Modbus by the bluetti_mqtt community.
#
# AC300 FC=16 push cycle (~25s total, 5 blocks):
#   start_addr=0:    regs 0-35   (device type, serial number, versions)
#   start_addr=36:   regs 36-69  (power, SOC, output switches)
#   start_addr=70:   regs 70-129 (AC/DC details, pack data)
#   start_addr=130:  regs 130+   (extended data)
#   start_addr=3000: regs 3000-3061 (control registers, switch states)

# Battery state enum (register 97 — pack_status)
BATTERY_STATE_MAP = {
    0: "standby",
    1: "charging",
    2: "discharging",
}

# Register address → (field_name, transform)
# transform: "u16"=raw, "div10"=/10.0, "div100"=/100.0, "bool"=0/1, "battery_state"=enum
_AC300_REGISTER_MAP: dict[int, tuple[str, str]] = {
    # Block start_addr=36 (registers 36-69)
    36: ("dc_input_power", "u16"),           # PV input power (W)
    37: ("ac_input_power", "u16"),           # Grid/AC input power (W)
    38: ("ac_output_power", "u16"),          # AC output power (W)
    39: ("dc_output_power", "u16"),          # DC output power (W)
    43: ("total_battery_percent", "u16"),    # Aggregate SOC (%)
    48: ("ac_output_on", "bool"),            # AC output switch
    49: ("dc_output_on", "bool"),            # DC output switch
    # Block start_addr=70 (registers 70-129)
    86: ("pv_input_voltage", "div10"),       # PV panel voltage (V)
    87: ("pv_input_power", "u16"),           # PV panel power (W)
    88: ("pv_input_current", "div10"),       # PV panel current (A)
    91: ("pack_num_max", "u16"),             # Number of pack slots (hardware max)
    92: ("total_battery_voltage", "div10"),  # Aggregate voltage (V)
    93: ("total_battery_current", "div10"),  # Aggregate current (A)
    96: ("pack_num", "u16"),                 # Currently reported pack index
    97: ("pack_status", "battery_state"),    # 0=standby, 1=charge, 2=discharge
    98: ("pack_voltage", "div100"),          # Current pack voltage (V)
    99: ("pack_battery_percent", "u16"),     # Current pack SOC (%)
    # Block start_addr=3000 (registers 3000-3061)
    3007: ("ctrl_ac_switch", "bool"),
    3008: ("ctrl_dc_switch", "bool"),
}


def parse_fc16_registers(start_addr: int, register_data: bytes) -> dict[str, Any]:
    """Parse FC=16 register data using the AC300 register map.

    FC=16 telemetry pushes contain consecutive register values starting
    at start_addr. Each register is 2 bytes (u16, big-endian).

    Returns dict of field_name → parsed_value for all known registers
    found in the data block.
    """
    result: dict[str, Any] = {}
    num_regs = len(register_data) // 2

    for offset in range(num_regs):
        reg_addr = start_addr + offset
        entry = _AC300_REGISTER_MAP.get(reg_addr)
        if entry is None:
            continue

        field_name, transform = entry
        raw = _u16(register_data, offset * 2)

        if transform == "u16":
            result[field_name] = raw
        elif transform == "div10":
            result[field_name] = raw / 10.0
        elif transform == "div100":
            result[field_name] = raw / 100.0
        elif transform == "bool":
            result[field_name] = bool(raw)
        elif transform == "battery_state":
            result["pack_status_raw"] = raw
            result["charging_status"] = BATTERY_STATE_MAP.get(
                raw, f"unknown({raw})"
            )

    return result


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


# ---------------------------------------------------------------------------
# PackMainInfo parser — register 6000 (ProtocolParserV2.java:parsePackMainInfo)
# ---------------------------------------------------------------------------

def parse_pack_main_info(data: bytes) -> dict[str, Any]:
    """Parse PackMainInfo register values into named fields.

    Returns aggregate battery pack data: total voltage, current, SOC, SOH,
    temperature, charge/discharge times, and pack count/online mask.
    """
    result: dict[str, Any] = {}

    if len(data) < 20:
        return result

    result["pack_volt_type"] = _u16(data, 0)
    if len(data) > 3:
        result["pack_count"] = data[3]
    if len(data) > 5:
        result["pack_online_mask"] = _u16(data, 4)
    result["pack_total_voltage"] = _u16(data, 6) / 10.0
    result["pack_total_current"] = _s16(data, 8) / 10.0
    if len(data) > 11:
        result["pack_total_soc"] = data[11]
    if len(data) > 13:
        result["pack_total_soh"] = data[13]
    if len(data) > 15:
        result["pack_average_temp"] = _u16(data, 14) - 40
    if len(data) > 17:
        result["pack_running_status"] = data[17]
    if len(data) > 19:
        result["pack_charging_status"] = data[19]
        result["pack_charging_status_text"] = CHARGING_STATUS_MAP.get(
            data[19], f"unknown({data[19]})"
        )

    if len(data) > 35:
        result["charge_full_time"] = _u16(data, 34)
    if len(data) > 37:
        result["discharge_empty_time"] = _u16(data, 36)

    return result


# ---------------------------------------------------------------------------
# PackItemInfo parser — register 6100 (ProtocolParserV2.java:parsePackItemInfo)
# ---------------------------------------------------------------------------

def parse_inv_base_settings(data: bytes) -> dict[str, Any]:
    """Parse V2 inverter base settings (reg 2000) — authoritative switch state.

    The V2 homeData ctrl bits do not track output state reliably; this block is
    what the app itself reads back. Byte offsets into the Modbus data payload:
        [21] ctrl inverter   [23] ctrl AC   [25] ctrl DC   (each 0 or 1)

    Verified live: writing 1 to reg 2011 flips [23] from 0 to 1.

    Returns an empty dict for payloads too short to be this block, so a
    different register's response is never misread as switch state.
    """
    if len(data) < 26:
        return {}
    return {
        "ctrl_inverter": bool(data[21]),
        "ctrl_ac_switch": bool(data[23]),
        "ctrl_dc_switch": bool(data[25]),
    }


def parse_pack_item_info_v2(data: bytes) -> dict[str, Any]:
    """Parse a V2 (protocolVer >= 2000) per-pack record from reg 6100.

    Byte offsets into the Modbus data payload (header/CRC already stripped):
        [1]      pack id
        [2:14]   model, ASCII byte-swapped per register ("PA03" -> "AP300")
        [14:22]  serial (registers reversed, decimal)
        [22:24]  voltage / 100
        [24:26]  current / 10 (the app leaves this unsigned)
        [27]     SOC %          [29]  SOH %
        [30:32]  temperature - 40
        [49] running status     [51] charging status
        [105] cell count        [107] NTC count      [109] BMU count

    Differs from the V1 layout in the ASCII/SN encoding, the /100 voltage
    divisor and the -40 (not -41) temperature offset.
    """
    result: dict[str, Any] = {}
    if len(data) < 32:
        return result

    result["pack_id"] = data[1]
    result["pack_type"] = ascii_swapped(data[2:14])
    result["pack_sn"] = device_sn_from_registers(data[14:22])
    result["pack_voltage"] = _u16(data, 22) / 100.0
    result["pack_current"] = _u16(data, 24) / 10.0

    if len(data) > 27:
        result["pack_soc"] = data[27]
    if len(data) > 29:
        result["pack_soh"] = data[29]
    if len(data) > 31:
        raw_temp = _u16(data, 30)
        # An all-zero record would otherwise report a bogus -40 °C.
        result["pack_average_temp"] = raw_temp - 40 if raw_temp else None
    if len(data) > 49:
        result["pack_running_status"] = data[49]
    if len(data) > 51:
        result["pack_charging_status"] = data[51]
        result["pack_charging_status_text"] = CHARGING_STATUS_MAP.get(
            data[51], f"unknown({data[51]})"
        )
    if len(data) > 105:
        result["total_cell_count"] = data[105]
    if len(data) > 107:
        result["ntc_cell_count"] = data[107]
    if len(data) > 109:
        result["bmu_count"] = data[109]

    return result


def parse_pack_item_info(data: bytes) -> dict[str, Any]:
    """Parse PackItemInfo register values for a single battery pack.

    Returns per-pack data: pack_id, type, serial number, voltage, current,
    SOC, SOH, temperature, and charging status.
    """
    result: dict[str, Any] = {}

    if len(data) < 26:
        return result

    result["pack_id"] = data[1]
    result["pack_type"] = _ascii(data, 2, 12)
    result["pack_sn"] = _ascii(data, 14, 8)
    result["pack_voltage"] = _u16(data, 22) / 100.0
    result["pack_current"] = _s16(data, 24) / 10.0

    if len(data) > 27:
        result["pack_soc"] = data[27]
    if len(data) > 29:
        result["pack_soh"] = data[29]
    if len(data) > 31:
        result["pack_average_temp"] = _u16(data, 30) - 40

    if len(data) > 49:
        result["pack_running_status"] = data[49]
    if len(data) > 51:
        result["pack_charging_status"] = data[51]
        result["pack_charging_status_text"] = CHARGING_STATUS_MAP.get(
            data[51], f"unknown({data[51]})"
        )

    return result
