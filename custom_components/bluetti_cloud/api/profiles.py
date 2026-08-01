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
        pushes_telemetry: True if the device pushes FC=16 frames unprompted.
        slave_addr: Modbus slave address for read/write frames.
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


# AP300 (APEX 300): REST-only. protocolVer 2015 uses a newer IoT protocol the
# current MQTT/Modbus implementation does not speak (discovery 2026-08-01: the
# device returns no frames to FC=03 reads and pushes nothing unprompted), but
# its cloud session is online and getDeviceLastAlive fully populates SOC,
# voltage, power, switch states, and energy over REST. No MQTT, no control.
AP300_PROFILE = DeviceProfile(
    model="AP300",
    protocol_ver_min=0,
    data_path="rest_only",
    pushes_telemetry=False,
    slave_addr=1,
    read_blocks=(),
    pack_select_reg=None,
    ac_switch_reg=None,
    dc_switch_reg=None,
    switch_encoding="simple",
)


# Registry of known profiles, most specific first. Extended as models are added.
_PROFILES: tuple[DeviceProfile, ...] = (AC300_PROFILE, AP300_PROFILE)


def get_profile(model: str, protocol_ver: int) -> DeviceProfile:
    """Return the device profile for a model + protocol version.

    Falls back to the AC300 profile for unknown models, preserving the
    integration's original behavior.
    """
    candidates = [
        p
        for p in _PROFILES
        if p.model == model and protocol_ver >= p.protocol_ver_min
    ]
    if candidates:
        # Highest protocol_ver_min wins (most specific match).
        return max(candidates, key=lambda p: p.protocol_ver_min)
    return AC300_PROFILE
