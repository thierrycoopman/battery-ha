"""Tests for INV_BASE_SETTINGS (reg 2000) — the authoritative V2 switch state.

Verified live: writing 1 to reg 2011 flips ctrlAC in this block from 0 to 1.
"""

from custom_components.bluetti_cloud.api.modbus import (
    INV_BASE_SETTINGS,
    parse_inv_base_settings,
)


def test_register_constant():
    assert INV_BASE_SETTINGS == 2000


def _block(ctrl_inverter: int, ctrl_ac: int, ctrl_dc: int) -> bytes:
    data = bytearray(60)
    data[21] = ctrl_inverter
    data[23] = ctrl_ac
    data[25] = ctrl_dc
    return bytes(data)


def test_parses_control_states():
    parsed = parse_inv_base_settings(_block(0, 1, 0))
    assert parsed["ctrl_ac_switch"] is True
    assert parsed["ctrl_dc_switch"] is False
    assert parsed["ctrl_inverter"] is False


def test_parses_all_on():
    parsed = parse_inv_base_settings(_block(1, 1, 1))
    assert parsed["ctrl_ac_switch"] is True
    assert parsed["ctrl_dc_switch"] is True
    assert parsed["ctrl_inverter"] is True


def test_rejects_short_payload():
    # Other register blocks must not be misread as switch state.
    assert parse_inv_base_settings(bytes(10)) == {}
