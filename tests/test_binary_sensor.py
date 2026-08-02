"""Tests for the Bluetti Cloud binary sensor platform."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE, DeviceProfile
from custom_components.bluetti_cloud.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    OUTPUT_STATE_DESCRIPTIONS,
    async_setup_entry,
)

_UNCONTROLLABLE = DeviceProfile(model="RO", protocol_ver_min=0, data_path="rest_only")


def _coordinator():
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator._device_info = {}
    coordinator.profile_for.side_effect = (
        lambda sn: AC300_PROFILE if "AC300" in sn else _UNCONTROLLABLE
    )
    return coordinator


@pytest.mark.asyncio
async def test_rest_only_device_gets_output_state_sensors():
    """A non-controllable device gets base sensors + output-state sensors."""
    coordinator = _coordinator()
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["ROSN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    # +1 for the always-present Device Reachable sensor
    assert len(added) == len(BINARY_SENSOR_DESCRIPTIONS) + len(OUTPUT_STATE_DESCRIPTIONS) + 1
    keys = {e.entity_description.key for e in added}
    assert "ac_output_state" in keys
    assert "dc_output_state" in keys


@pytest.mark.asyncio
async def test_mqtt_device_gets_no_output_state_sensors():
    """AC300 (mqtt+rest) gets only the base binary sensors (it has switches)."""
    coordinator = _coordinator()
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["AC300SN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    assert len(added) == len(BINARY_SENSOR_DESCRIPTIONS) + 1  # + Device Reachable
    keys = {e.entity_description.key for e in added}
    assert "ac_output_state" not in keys
    assert "reachable" in keys


@pytest.mark.asyncio
async def test_node_binary_sensors_created_from_node_list():
    """Sub-device nodes become connectivity binary sensors."""
    from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE
    nodes = [
        {"slave_addr": 0, "model": 6, "model_name": "AP300", "is_battery": False,
         "online": True, "warning": False, "error": False, "sn": "aa"},
        {"slave_addr": 11, "model": 3007, "model_name": "D1 Hub (HD1)",
         "is_battery": False, "online": True, "warning": False, "error": False, "sn": "bb"},
        {"slave_addr": 51, "model": 4005, "model_name": "Battery", "is_battery": True,
         "online": True, "warning": False, "error": False, "sn": "cc"},
    ]
    coordinator = MagicMock()
    coordinator.data = {"SN": {"nodes": nodes}}
    coordinator._device_info = {}
    coordinator.profile_for.return_value = AC300_PROFILE  # controllable → no output sensors
    coordinator.get_nodes.return_value = nodes

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["SN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    from custom_components.bluetti_cloud.entity import BluettiSubDeviceEntity

    sub = [e for e in added if isinstance(e, BluettiSubDeviceEntity)]
    # Each of the 3 nodes gets a connectivity and a fault sensor.
    assert len(sub) == 6
    battery = next(
        e for e in sub if e._slave_addr == 51 and e.unique_id.endswith("online")
    )
    assert battery.is_on is True
    assert battery.extra_state_attributes["type"] == "battery"
    hub = next(
        e for e in sub if e._slave_addr == 11 and e.unique_id.endswith("online")
    )
    assert hub.extra_state_attributes["model"] == "D1 Hub (HD1)"
    # Each sub-device is registered as its own device under the parent.
    assert hub.device_info["via_device"] == ("bluetti_cloud", "SN")
