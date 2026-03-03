"""Tests for Bluetti Cloud switch platform."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bluetti_cloud.switch import (
    SWITCH_DESCRIPTIONS,
    BluettiCloudSwitch,
)
from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator


@pytest.fixture
def coordinator_data():
    return {
        "AC300FAKESERIAL001": {
            "online": True,
            "device_name": "Winenne",
            "device_type": "AC300",
            "battery_soc": 85,
            "total_battery_percent": 85,
            "power_pv_in": 250,
            "power_grid_in": 0,
            "power_ac_out": 150,
            "power_dc_out": 30,
            "ac_switch": True,
            "dc_switch": False,
        }
    }


@pytest.fixture
def mock_coordinator(coordinator_data):
    coordinator = MagicMock(spec=BluettiCloudCoordinator)
    coordinator.data = coordinator_data
    coordinator.last_update_success = True
    coordinator.client = AsyncMock()
    coordinator.client.control_device = AsyncMock(
        return_value={"msgCode": 0, "data": True}
    )
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def test_ac_switch_is_on(mock_coordinator):
    """Test AC switch reads state from coordinator."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert switch.is_on is True
    assert switch.unique_id == "AC300FAKESERIAL001_ac_switch"


def test_dc_switch_is_off(mock_coordinator):
    """Test DC switch reads state from coordinator."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dc_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert switch.is_on is False


@pytest.mark.asyncio
async def test_turn_on_calls_api(mock_coordinator):
    """Test that turn_on sends the correct API command."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    await switch.async_turn_on()

    mock_coordinator.client.control_device.assert_called_once_with(
        "AC300FAKESERIAL001", "SetCtrlAcSwitch", "1"
    )
    mock_coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_turn_off_calls_api(mock_coordinator):
    """Test that turn_off sends the correct API command."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dc_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    await switch.async_turn_off()

    mock_coordinator.client.control_device.assert_called_once_with(
        "AC300FAKESERIAL001", "SetCtrlDcSwitch", "0"
    )
    mock_coordinator.async_request_refresh.assert_called_once()


def test_switch_unavailable_when_offline(mock_coordinator):
    """Test that switches are unavailable when device is offline."""
    mock_coordinator.data["AC300FAKESERIAL001"]["online"] = False
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert switch.available is False


def test_switch_descriptions_have_fn_codes():
    """Verify all switch descriptions have fn_code for API control."""
    for desc in SWITCH_DESCRIPTIONS:
        assert desc.fn_code
        assert desc.data_key
        assert desc.key
