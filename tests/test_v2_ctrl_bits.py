"""On V2 devices the homeData ctrl bits must not drive user-facing state.

Measured on real hardware: toggling ECO from off to on left the ctrl word
without an eco bit set, while an unrelated bit moved on its own. The bits also
read 0 for an output that is demonstrably on. Whatever their true layout, they
do not track state on this protocol version — so PV and grid state come from
the sources that do (REST, and the settings blocks), not from these bits.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE, AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

SN = "SN"


def _manager(profile):
    coordinator = MagicMock()
    coordinator.data = {SN: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = profile
    return BluettiMqttManager(coordinator)


def _home_data_with_ctrl(ctrl: int) -> bytes:
    data = bytearray(124)
    data[4] = 0
    data[5] = 94                      # battery_soc
    data[48] = (ctrl >> 8) & 0xFF
    data[49] = ctrl & 0xFF
    return bytes(data)


def test_v2_home_data_does_not_set_any_switch_state():
    """All four switch keys must be left to authoritative sources on V2."""
    mgr = _manager(AP300_PROFILE)
    # Every ctrl bit set — none of it should reach the switch keys.
    mgr._process_home_data(SN, _home_data_with_ctrl(0xFFFF))
    overlay = mgr.overlays[SN]
    for key in ("ac_switch", "dc_switch", "pv_switch", "grid_switch"):
        assert key not in overlay, f"{key} must not come from V2 ctrl bits"


def test_v2_home_data_still_provides_its_reliable_fields():
    mgr = _manager(AP300_PROFILE)
    mgr._process_home_data(SN, _home_data_with_ctrl(0x0000))
    assert mgr.overlays[SN]["battery_soc"] == 94


def test_v1_home_data_still_uses_ctrl_bits():
    """The AC300 path is unchanged — those bits are how it reports state."""
    mgr = _manager(AC300_PROFILE)
    mgr._process_home_data(SN, _home_data_with_ctrl(0b0101))  # ac + pv
    overlay = mgr.overlays[SN]
    assert overlay["ac_switch"] is True
    assert overlay["pv_switch"] is True
