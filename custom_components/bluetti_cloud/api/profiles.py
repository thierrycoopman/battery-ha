"""Declarative per-model device profiles.

A profile captures everything model-specific about how a Bluetti device is
talked to: its data path (MQTT+REST vs REST-only), whether it pushes telemetry
unprompted, its Modbus slave address, the FC=03 read blocks used for MQTT
polling, and its switch registers/encoding.

This replaces AC300-specific constants scattered through the coordinator with
data, so adding a device (e.g. the AP300 / APEX 300) is a profile entry rather
than new branching logic.

Profiles are matched on the model string reported by the cloud API
(`homeDevices[].model`) and the device's protocol version
(`homeDevices[].factoryProtocolVer`). Unknown models fall back to the AC300
profile, preserving the integration's original behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DataPath = Literal["mqtt+rest", "rest_only"]
SwitchEncoding = Literal["simple", "shifted"]


@dataclass(frozen=True)
class ReadBlock:
    """A FC=03 read block used to poll a device over MQTT.

    Attributes:
        name: Stable identifier (also the parser dispatch key by default).
        register: Modbus start register address.
        count: Number of 16-bit registers to read.
        parser_key: Key selecting the parser for the response payload.
    """

    name: str
    register: int
    count: int
    parser_key: str


@dataclass(frozen=True)
class DeviceProfile:
    """Model-specific behavior for a Bluetti device.

    Attributes:
        model: Cloud model string (e.g. "AC300", "AP300").
        protocol_ver_min: Minimum factoryProtocolVer this profile applies to.
        data_path: "mqtt+rest" (MQTT telemetry/control + REST) or "rest_only".
        pushes_telemetry: True if the device pushes FC=16 frames unprompted
            (V1). False means telemetry must be actively polled via FC=03.
        slave_addr: Modbus slave address for read/write frames (0 for 2nd-gen
            IoT / protocolVer >= 2000, 1 for older devices).
        iot_payload_ver: MQTT payload envelope version — 1.0 (legacy 0x01 +
            Modbus) or >= 1.1 (2nd-gen `01 F8 0F ...` envelope).
        read_blocks: FC=03 blocks polled over MQTT (empty for rest_only).
        pack_select_reg: Register to select a reporting pack, or None.
        ac_switch_reg: AC output control register, or None if not controllable.
        dc_switch_reg: DC output control register, or None if not controllable.
        switch_encoding: "simple" (0/1) or "shifted" (bit-encoded) writes.
    """

    model: str
    protocol_ver_min: int
    data_path: DataPath = "mqtt+rest"
    pushes_telemetry: bool = True
    slave_addr: int = 1
    iot_payload_ver: float = 1.0
    read_blocks: tuple[ReadBlock, ...] = field(default_factory=tuple)
    pack_select_reg: int | None = None
    ac_switch_reg: int | None = None
    dc_switch_reg: int | None = None
    switch_encoding: SwitchEncoding = "simple"

    @property
    def controllable(self) -> bool:
        """True if the device exposes controllable output switches."""
        return self.ac_switch_reg is not None or self.dc_switch_reg is not None


# AC300 (and compatible older models): MQTT+REST hybrid, FC=16 push, simple
# 0/1 switch writes at 3007/3008, FC=03 read blocks for home/pack data.
AC300_PROFILE = DeviceProfile(
    model="AC300",
    protocol_ver_min=0,
    data_path="mqtt+rest",
    pushes_telemetry=True,
    slave_addr=1,
    read_blocks=(
        ReadBlock("home_data", 100, 62, "home_data"),
        ReadBlock("pack_main_info", 6000, 34, "pack_main_info"),
        ReadBlock("pack_item_info", 6100, 90, "pack_item_info"),
    ),
    pack_select_reg=3006,
    ac_switch_reg=3007,
    dc_switch_reg=3008,
    switch_encoding="simple",
)


# AP300 (APEX 300): 2nd-generation IoT (protocolVer >= 2000). Poll-driven MQTT
# (no unprompted pushes) using the iotPayloadVer-1.2 envelope and Modbus slave 0.
# The V1 FC=03 register blocks (100/6000/6100) and V2 parsers apply as-is —
# verified live (homeData 531.3V/95%/2 packs, packMainInfo). Telemetry only for
# now; AC/DC control (V2 switch registers 2011/2012) is a later step, so the
# switch registers stay None and outputs surface as read-only binary sensors.
AP300_PROFILE = DeviceProfile(
    model="AP300",
    protocol_ver_min=0,
    data_path="mqtt+rest",
    pushes_telemetry=False,
    slave_addr=0,
    iot_payload_ver=1.2,
    read_blocks=(
        ReadBlock("home_data", 100, 62, "home_data"),
        ReadBlock("pack_main_info", 6000, 34, "pack_main_info"),
        ReadBlock("pack_item_info", 6100, 90, "pack_item_info"),
    ),
    pack_select_reg=None,
    ac_switch_reg=None,
    dc_switch_reg=None,
    switch_encoding="simple",
)


# Generic fallback for an unrecognised 2nd-generation IoT device (protocolVer
# >= 2000). Such devices need the V2 payload envelope and Modbus slave 0, so
# falling back to the V1 profile would produce frames they ignore. Telemetry
# registers are the common V2 blocks; control is left off because switch
# registers and value encoding vary per model and are unverified here.
GENERIC_V2_PROFILE = DeviceProfile(
    model="",
    protocol_ver_min=2000,
    data_path="mqtt+rest",
    pushes_telemetry=False,
    slave_addr=0,
    iot_payload_ver=1.2,
    read_blocks=(
        ReadBlock("home_data", 100, 62, "home_data"),
        ReadBlock("pack_main_info", 6000, 34, "pack_main_info"),
        ReadBlock("pack_item_info", 6100, 90, "pack_item_info"),
    ),
)

# Protocol version at/above which a device uses the 2nd-generation IoT stack.
PROTOCOL_VER_V2 = 2000

# Registry of known profiles, most specific first. Extended as models are added.
_PROFILES: tuple[DeviceProfile, ...] = (AC300_PROFILE, AP300_PROFILE)


def get_profile(model: str, protocol_ver: int) -> DeviceProfile:
    """Return the device profile for a model + protocol version.

    Unknown models fall back by protocol generation: >= 2000 gets the generic
    V2 profile (correct payload framing and slave address, telemetry only),
    anything older gets the AC300 profile — the integration's original behavior.
    """
    candidates = [
        p
        for p in _PROFILES
        if p.model == model and protocol_ver >= p.protocol_ver_min
    ]
    if candidates:
        # Highest protocol_ver_min wins (most specific match).
        return max(candidates, key=lambda p: p.protocol_ver_min)
    if protocol_ver >= PROTOCOL_VER_V2:
        return GENERIC_V2_PROFILE
    return AC300_PROFILE
