"""Replay recorded MQTT traffic through the real message path.

Every reliability bug this integration has had was a decoding or routing
mistake that only appeared with realistic traffic: a cell block arriving while
a pack read was outstanding, a frame from slave 0, an unsolicited push with no
start address. Tests that hand-build a parsed dict cannot catch those, because
they skip the very layers that got them wrong.

This harness starts from **wire bytes** — the exact payload the broker would
deliver — and drives them through envelope stripping, CRC, block
identification, routing and state accumulation, in that order. Building a frame
here means computing its CRC, so a frame that could not exist on the wire
cannot be asserted against either.

It also removes the need to test against the live device. The broker allows
roughly one session per account, so a test connection displaces the user's Home
Assistant; replaying captured frames costs nothing and is repeatable.

    session = ReplaySession()
    session.push_fc03(cell_block, slave=0)
    assert session.data["cell_voltage_delta"] < 0.05
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.modbus import (
    NODE_INFO,
    PROTOCOL_BYTE,
    crc16_modbus,
    parse_mqtt_payload,
)
from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

TOPIC = "PUB/AP300/2616113487436"


def _frame(slave: int, body: bytes, *, v2: bool) -> bytes:
    """Wrap a Modbus body in a CRC'd frame and the right payload envelope."""
    rtu = bytes([slave]) + body
    rtu += crc16_modbus(rtu)
    if v2:
        # iotPayloadVer 1.2: a 10-byte 01 F8 ... header precedes the frame.
        return bytes([PROTOCOL_BYTE, 0xF8, 0x0F, 0, 0, 0, 0, 0, 0, 0]) + rtu
    return bytes([PROTOCOL_BYTE]) + rtu


def fc03_response(register_data: bytes, slave: int = 0, v2: bool = True) -> bytes:
    """A read reply: what the device sends when answering a poll."""
    body = bytes([0x03, len(register_data)]) + register_data
    return _frame(slave, body, v2=v2)


def fc16_push(
    start_addr: int, register_data: bytes, slave: int = 0, v2: bool = True
) -> bytes:
    """An unprompted telemetry push, which this hardware sends constantly."""
    count = len(register_data) // 2
    body = (
        bytes([0x10])
        + start_addr.to_bytes(2, "big")
        + count.to_bytes(2, "big")
        + bytes([len(register_data)])
        + register_data
    )
    return _frame(slave, body, v2=v2)


def fc06_echo(register: int, value: int, slave: int = 0, v2: bool = True) -> bytes:
    """The device's confirmation that a write took effect."""
    body = bytes([0x06]) + register.to_bytes(2, "big") + value.to_bytes(2, "big")
    return _frame(slave, body, v2=v2)


def error_response(original_fc: int, code: int, slave: int = 0, v2: bool = True) -> bytes:
    """A refusal — the device rejecting a read or write."""
    return _frame(slave, bytes([original_fc | 0x80, code]), v2=v2)


class ReplaySession:
    """A manager fed from the wire, with the traffic it saw kept for asserting."""

    def __init__(self, sn: str = "AP3002616113487436", model: str = "AP300") -> None:
        self.sn = sn
        coordinator = MagicMock()
        coordinator.data = {sn: {"device_type": model, "sub_sn": "2616113487436"}}
        coordinator.profile_for.return_value = AP300_PROFILE
        self.coordinator = coordinator
        self.manager = BluettiMqttManager(coordinator)
        self.manager._topic_to_sn[TOPIC] = sn
        self.unparseable: list[bytes] = []

    def deliver(self, payload: bytes) -> None:
        """Hand one wire payload to the manager, exactly as the broker would."""
        parsed = parse_mqtt_payload(payload)
        if parsed is None:
            # A corrupt frame must be dropped, not decoded — record it so a
            # test can assert the drop rather than the harness hiding it.
            self.unparseable.append(payload)
            return
        self.manager._handle_mqtt_message(TOPIC, parsed)

    def replay(self, payloads: list[bytes]) -> None:
        """Deliver a recorded sequence in order."""
        for payload in payloads:
            self.deliver(payload)

    # Convenience wrappers so tests read as traffic, not as frame construction.

    def push_fc03(self, register_data: bytes, slave: int = 0) -> None:
        self.deliver(fc03_response(register_data, slave))

    def push_fc16(self, start_addr: int, register_data: bytes, slave: int = 0) -> None:
        self.deliver(fc16_push(start_addr, register_data, slave))

    def push_echo(self, register: int, value: int, slave: int = 0) -> None:
        self.deliver(fc06_echo(register, value, slave))

    def discover_nodes(self, node_info: bytes) -> None:
        """Deliver the expansion registry, which arrives as an FC=16 push.

        Per-pack detail only attaches to a node the device has already
        announced, so a replay that skips this discards its pack frames — the
        same way a real session would between a reconnect and the next node
        poll.
        """
        self.push_fc16(NODE_INFO, node_info)

    @property
    def data(self) -> dict[str, Any]:
        """Everything the manager believes about the device after the replay."""
        return self.manager.overlays.get(self.sn, {})

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return self.data.get("nodes", [])
