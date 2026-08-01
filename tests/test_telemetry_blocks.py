"""Parsers for the V2 telemetry blocks the device pushes.

Verified against real payloads captured from a live AP300 (tests/fixtures/
apex300/blocks/). Values that are zero in the fixtures reflect an idle device;
the offsets are pinned by the fields that do carry data (cell voltages, grid
import energy, PV string count).
"""

import pathlib

from custom_components.bluetti_cloud.api.modbus import (
    parse_inv_base_info,
    parse_inv_grid_info,
    parse_inv_inv_info,
    parse_inv_load_info,
    parse_inv_pv_info,
    parse_pack_cells,
)

BLOCKS = pathlib.Path(__file__).parent / "fixtures" / "apex300" / "blocks"


def _block(addr: int) -> bytes:
    return bytes.fromhex((BLOCKS / f"block_{addr}.hex").read_text().strip())


def test_pack_cells_real_payload():
    """16 LiFePO4 cells at ~3.32V — the strongest confirmation of the layout."""
    cells = parse_pack_cells(_block(6300))
    assert cells["cell_count"] == 16
    assert cells["ntc_count"] == 4
    assert len(cells["cell_voltages"]) == 16
    # LiFePO4 resting voltage
    assert 3.0 < cells["cell_voltages"][0] < 3.7
    assert cells["cell_voltage_min"] <= cells["cell_voltage_max"]
    # A balanced pack has a small spread
    assert cells["cell_voltage_delta"] < 0.5


def test_grid_info_real_payload():
    grid = parse_inv_grid_info(_block(1300))
    assert grid["grid_import_energy"] == 3.3  # real accumulated value
    assert grid["grid_phases"] == 1
    assert grid["grid_frequency"] == 0.0  # grid disconnected while idle


def test_pv_info_real_payload():
    pv = parse_inv_pv_info(_block(1200))
    assert pv["pv_dc_string_count"] == 2
    assert pv["pv_ac_string_count"] == 0
    assert len(pv["pv_strings"]) == 2
    assert pv["pv_total_power"] == 0  # no sun during capture


def test_load_info_real_payload():
    load = parse_inv_load_info(_block(1400))
    assert load["dc_load_power"] == 0
    assert load["ac_load_power"] == 0
    assert "dc_load_energy" in load


def test_inv_info_real_payload():
    inv = parse_inv_inv_info(_block(1500))
    assert "inverter_frequency" in inv
    assert inv["inverter_phases"] == 1


def test_base_info_temperatures_are_none_when_unreported():
    """An idle device reports raw 0; that must not surface as -40 C."""
    base = parse_inv_base_info(_block(1100))
    assert base["ambient_temp"] is None
    assert base["inverter_temp"] is None


def test_base_info_temperature_decoding():
    data = bytearray(160)
    data[102:104] = (65).to_bytes(2, "big")   # 65 - 40 = 25 C
    data[104:106] = (70).to_bytes(2, "big")   # 30 C
    base = parse_inv_base_info(bytes(data))
    assert base["ambient_temp"] == 25
    assert base["inverter_temp"] == 30


def test_parsers_reject_short_payloads():
    for fn in (parse_inv_base_info, parse_inv_pv_info, parse_inv_grid_info,
               parse_inv_load_info, parse_inv_inv_info, parse_pack_cells):
        assert fn(bytes(4)) == {}
