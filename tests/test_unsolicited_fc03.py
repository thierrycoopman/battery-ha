"""Unsolicited FC=03 frames must not be blindly parsed as homeData.

The device pushes FC=03 frames with no start_addr and no pending request. The
old code assumed any such frame was homeData (reg 100), so a 208-byte pack
frame was decoded with the 124-byte homeData layout — producing garbage like
battery_soc=12336 (0x3030, ASCII "00") and pack_count=16 (the cell count).
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager


def _manager():
    coordinator = MagicMock()
    coordinator.data = {"SN": {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    return BluettiMqttManager(coordinator)


def _fc03(data: bytes) -> dict:
    return {"function_code": 0x03, "register_data": data}


def test_unsolicited_frame_of_wrong_length_is_ignored():
    mgr = _manager()
    # 208 bytes = a pack-item frame, not homeData
    mgr._handle_telemetry_data("SN", _fc03(bytes(208)))
    overlay = mgr.overlays.get("SN", {})
    assert "battery_soc" not in overlay


def test_unsolicited_home_data_length_is_still_parsed():
    mgr = _manager()
    data = bytearray(124)
    data[4] = 0          # soc high byte
    data[5] = 94         # battery_soc = 94
    mgr._handle_telemetry_data("SN", _fc03(bytes(data)))
    assert mgr.overlays["SN"]["battery_soc"] == 94


def test_pending_request_still_wins():
    """An explicit poll routes by its register, regardless of length."""
    mgr = _manager()
    mgr._pending_request = (2000, 0)
    data = bytearray(60)
    data[23] = 1  # ctrlAC on
    mgr._handle_telemetry_data("SN", _fc03(bytes(data)))
    assert mgr.overlays["SN"]["ac_switch"] is True
