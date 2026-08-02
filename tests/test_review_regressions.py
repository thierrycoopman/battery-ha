"""Regressions found by an independent review of the control/telemetry work."""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud import PLATFORMS
from custom_components.bluetti_cloud.api.modbus import (
    parse_inv_adv_settings,
    parse_inv_base_settings,
)
from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager


def _manager():
    coordinator = MagicMock()
    coordinator.data = {"SN": {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    return BluettiMqttManager(coordinator)


def test_select_platform_is_registered():
    """The charging-mode select is never created if SELECT isn't forwarded."""
    assert "select" in [p.value for p in PLATFORMS]


def test_eco_state_reaches_the_overlay():
    """Reg 2000 carries ECO state; dropping it left the ECO entities unknown."""
    mgr = _manager()
    data = bytearray(60)
    data[35] = 1   # ac eco on
    data[37] = 3   # 3 hours
    data[39] = 25  # 25 W
    mgr._process_inv_base_settings("SN", bytes(data))
    overlay = mgr.overlays["SN"]
    assert overlay["ac_eco"] is True
    assert overlay["ac_eco_auto_off"] == 3
    assert overlay["ac_eco_power"] == 25


def test_home_data_does_not_clobber_v2_switch_state():
    """V2 homeData ctrl bits are unreliable and must not overwrite reg 2000."""
    mgr = _manager()
    # Authoritative state: AC on.
    base = bytearray(60)
    base[23] = 1
    mgr._process_inv_base_settings("SN", bytes(base))
    assert mgr.overlays["SN"]["ac_switch"] is True

    # A homeData push whose ctrl bits still read off must not flip it back.
    home = bytearray(124)
    mgr._process_home_data("SN", bytes(home))
    assert mgr.overlays["SN"]["ac_switch"] is True


def test_charging_mode_is_read_back():
    data = bytearray(60)
    data[41] = 2  # turbo
    assert parse_inv_base_settings(bytes(data))["charging_mode_setting"] == "turbo"


def test_grid_and_feed_state_are_read_back():
    data = bytearray(40)
    data[15] = 1  # grid charging on
    data[17] = 0  # feed-in off
    parsed = parse_inv_adv_settings(bytes(data))
    assert parsed["grid_charge"] is True
    assert parsed["feed_in"] is False
