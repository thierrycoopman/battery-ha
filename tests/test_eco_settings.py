"""ECO mode: on/off switches plus their numeric parameters.

Registers and ranges from the app (DeviceSettingsECOActivity):
  2014 DC eco on/off      2015 DC auto-off 1-4 h    2016 DC power 5-20 W
  2017 AC eco on/off      2018 AC auto-off 1-4 h    2019 AC power 10-40 W
"""

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    AC_ECO_MODE,
    DC_ECO_MODE,
    SETTING_RANGES,
    build_setting_payload,
    build_switch_payload,
)


def test_eco_switches_are_controllable():
    for reg in (DC_ECO_MODE, AC_ECO_MODE):
        payload = build_switch_payload(reg, 1, slave_addr=0, payload_ver=1.2)
        assert payload[:3] == bytes.fromhex("01f80f")


def test_eco_register_addresses():
    assert DC_ECO_MODE == 2014
    assert AC_ECO_MODE == 2017


def test_setting_ranges_match_the_app():
    assert SETTING_RANGES[2015] == (1, 4)    # DC auto-off hours
    assert SETTING_RANGES[2016] == (5, 20)   # DC eco power W
    assert SETTING_RANGES[2018] == (1, 4)    # AC auto-off hours
    assert SETTING_RANGES[2019] == (10, 40)  # AC eco power W


@pytest.mark.parametrize("register,value", [(2015, 2), (2016, 12), (2019, 25)])
def test_valid_settings_build(register, value):
    payload = build_setting_payload(register, value, slave_addr=0, payload_ver=1.2)
    # V2 envelope + FC=06 write of the value
    assert payload[:3] == bytes.fromhex("01f80f")
    assert payload[11] == 0x06


@pytest.mark.parametrize("register,value", [
    (2015, 0), (2015, 5),      # hours out of 1-4
    (2016, 4), (2016, 21),     # DC watts out of 5-20
    (2019, 9), (2019, 41),     # AC watts out of 10-40
])
def test_out_of_range_settings_are_refused(register, value):
    with pytest.raises(ValueError, match="out of range"):
        build_setting_payload(register, value, slave_addr=0, payload_ver=1.2)


def test_unknown_setting_register_refused():
    with pytest.raises(ValueError, match="not a settable register"):
        build_setting_payload(2408, 1, slave_addr=0, payload_ver=1.2)
