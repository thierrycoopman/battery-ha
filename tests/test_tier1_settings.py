"""Tier-1 settables: charging mode, grid charging, feed-in, and limits.

Registers and encodings from the app:
  2020 CHARGING_MODE     0=Standard, 1=Silent, 2=Turbo, 4=Custom
  2207 CTRL_GRID         0/1  grid charging enable (protocolVer >= 2015)
  2208 CTRL_FEED         0/1  feed-in / export enable
  2213 GRID_MAX_POWER    W,  AP300 300-6000
  2215 FEED_MAX_POWER    W
  2023 SYS_SOC_HIGH      %,  1-100
"""

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    CHARGING_MODE,
    CHARGING_MODES,
    CTRL_FEED,
    CTRL_GRID,
    SETTING_RANGES,
    build_setting_payload,
    build_switch_payload,
)


def test_register_addresses():
    assert CHARGING_MODE == 2020
    assert CTRL_GRID == 2207
    assert CTRL_FEED == 2208


def test_grid_and_feed_are_switchable():
    for reg in (CTRL_GRID, CTRL_FEED):
        assert build_switch_payload(reg, 1, slave_addr=0, payload_ver=1.2)


def test_charging_modes_match_the_app():
    assert CHARGING_MODES == {
        0: "standard",
        1: "silent",
        2: "turbo",
        4: "custom",
    }


@pytest.mark.parametrize("value", [0, 1, 2, 4])
def test_valid_charging_modes_build(value):
    assert build_setting_payload(CHARGING_MODE, value, slave_addr=0, payload_ver=1.2)


@pytest.mark.parametrize("value", [3, 5, 99])
def test_invalid_charging_mode_refused(value):
    with pytest.raises(ValueError):
        build_setting_payload(CHARGING_MODE, value, slave_addr=0, payload_ver=1.2)


def test_grid_power_range():
    assert SETTING_RANGES[2213] == (300, 6000)
    with pytest.raises(ValueError, match="out of range"):
        build_setting_payload(2213, 100, slave_addr=0, payload_ver=1.2)
    assert build_setting_payload(2213, 3000, slave_addr=0, payload_ver=1.2)


def test_soc_high_limit_range():
    assert SETTING_RANGES[2023] == (1, 100)
    with pytest.raises(ValueError, match="out of range"):
        build_setting_payload(2023, 101, slave_addr=0, payload_ver=1.2)
