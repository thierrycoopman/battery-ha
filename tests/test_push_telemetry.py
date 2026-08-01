"""Tests for V2 push telemetry handling.

The AP300 streams FC=16 pushes unprompted (~1 every 2s, incl. homeData reg 100
and switch state reg 2000). Those must be consumed with the V2 parsers, never
the V1 (AC300) register map.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE, AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager


def _manager(profile):
    coordinator = MagicMock()
    coordinator.data = {"SN": {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = profile
    mgr = BluettiMqttManager(coordinator)
    return mgr


def _push(start_addr, data):
    return {
        "function_code": 0x10,
        "start_addr": start_addr,
        "register_data": data,
    }


def test_v2_push_does_not_use_v1_register_map():
    """A V2 push must not flag the device as a V1 pusher (which would stop polling)."""
    mgr = _manager(AP300_PROFILE)
    # reg 2000 push carrying switch state
    data = bytearray(60)
    data[23] = 1  # ctrlAC on
    mgr._handle_write_multiple_data("SN", _push(2000, bytes(data)))

    assert "SN" not in mgr._fc16_devices
    assert mgr.overlays["SN"]["ac_switch"] is True


def test_v2_push_marks_device_streaming():
    mgr = _manager(AP300_PROFILE)
    assert mgr.is_streaming("SN") is False
    mgr._handle_write_multiple_data("SN", _push(2000, bytes(60)))
    assert mgr.is_streaming("SN") is True


def test_v1_push_still_uses_v1_map():
    """V1 devices keep the original FC=16 behaviour."""
    mgr = _manager(AC300_PROFILE)
    # start_addr 36 is a V1 AC300 block (power fields)
    mgr._handle_write_multiple_data("SN", _push(36, bytes(60)))
    # V1 path marks the device as an FC=16 pusher
    assert "SN" in mgr._fc16_devices


def test_streaming_is_per_device():
    mgr = _manager(AP300_PROFILE)
    mgr._handle_write_multiple_data("SN", _push(2000, bytes(60)))
    assert mgr.is_streaming("SN") is True
    assert mgr.is_streaming("OTHER") is False
