"""Safety tests for output-control writes.

Register 2013 is SYSTEM_POWER_OFF and sits directly next to DC_SWITCH (2012);
2206 is a factory reset. A bug that wrote those would shut down or reset a
user's unit, so control writes are restricted to a known allowlist.
"""

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    CONTROL_REGISTERS,
    build_switch_payload,
)


def test_known_control_registers_are_allowed():
    # V1 (AC300) and V2 (AP300) AC/DC switch registers.
    for reg in (3007, 3008, 2011, 2012):
        assert reg in CONTROL_REGISTERS


def test_dangerous_registers_are_not_controllable():
    for reg in (2013, 2206, 2233, 30901):
        assert reg not in CONTROL_REGISTERS


def test_switch_payload_rejects_non_control_register():
    # 2013 = system power off — must never be writable through this path.
    with pytest.raises(ValueError, match="not a control register"):
        build_switch_payload(2013, 1, slave_addr=0, payload_ver=1.2)


def test_switch_payload_rejects_out_of_range_value():
    with pytest.raises(ValueError, match="value"):
        build_switch_payload(2011, 5, slave_addr=0, payload_ver=1.2)


def test_v2_ac_on_matches_app_byte_sequence():
    # Exact frame the Bluetti app sends for AC output ON on a 2nd-gen device.
    payload = build_switch_payload(2011, 1, slave_addr=0, payload_ver=1.2)
    assert payload.hex() == "01f80f07db0000000000000607db00013894"


def test_v2_ac_off_matches_app_byte_sequence():
    payload = build_switch_payload(2011, 0, slave_addr=0, payload_ver=1.2)
    assert payload.hex() == "01f80f07db0000000000000607db0000f954"


def test_v2_dc_frames_match_app_byte_sequence():
    assert build_switch_payload(2012, 1, slave_addr=0, payload_ver=1.2).hex() == (
        "01f80f07dc0000000000000607dc00018955"
    )
    assert build_switch_payload(2012, 0, slave_addr=0, payload_ver=1.2).hex() == (
        "01f80f07dc0000000000000607dc00004895"
    )


def test_v1_switch_payload_keeps_legacy_framing():
    payload = build_switch_payload(3007, 1, slave_addr=1, payload_ver=1.0)
    assert payload[0] == 0x01      # legacy protocol byte
    assert payload[1] == 0x01      # slave 1
    assert payload[2] == 0x06      # FC=06
