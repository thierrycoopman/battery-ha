"""Tests for Bluetti Cloud switch platform (MQTT-based control)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bluetti_cloud.switch import (
    SWITCH_DESCRIPTIONS,
    BluettiCloudSwitch,
)
from custom_components.bluetti_cloud.api.modbus import AC_SWITCH, DC_SWITCH, SWITCH_ON, SWITCH_OFF
from custom_components.bluetti_cloud.api.mqtt_client import BluettiMqttError
from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator


@pytest.fixture
def coordinator_data():
    return {
        "AC300FAKESERIAL001": {
            "online": True,
            "device_name": "Winenne",
            "device_type": "AC300",
            "sub_sn": "FAKESERIAL001",
            "battery_soc": 85,
            "pack_voltage": None,
            "pack_current": None,
            "charging_status": None,
            "charge_time_remaining": None,
            "discharge_time_remaining": None,
            "pack_count": None,
            "inverter_count": None,
            "power_pv_in": 250,
            "power_grid_in": 0,
            "power_ac_out": 150,
            "power_dc_out": 30,
            "power_feed_back": 0,
            "ac_switch": True,
            "dc_switch": False,
            "pv_switch": None,
            "grid_switch": None,
            "energy_day": None,
            "energy_month": None,
            "energy_year": None,
            "energy_total": None,
            "last_update": None,
            "mqtt_active": True,
            "iot_session": None,
        }
    }


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client."""
    client = MagicMock()
    client.is_connected = True
    client.send_command = MagicMock()
    return client


@pytest.fixture
def mock_coordinator(coordinator_data, mock_mqtt_client):
    coordinator = MagicMock(spec=BluettiCloudCoordinator)
    coordinator.data = coordinator_data
    coordinator.last_update_success = True
    coordinator._device_info = {"AC300FAKESERIAL001": {"name": "Winenne", "model": "AC300"}}
    coordinator.mqtt_client = mock_mqtt_client
    return coordinator


def test_ac_switch_reads_state(mock_coordinator):
    """Test AC switch reads state from coordinator data."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert switch.is_on is True
    assert switch.unique_id == "AC300FAKESERIAL001_ac_switch"


def test_dc_switch_reads_state(mock_coordinator):
    """Test DC switch reads state from coordinator data."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dc_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert switch.is_on is False


@pytest.mark.asyncio
async def test_turn_on_sends_mqtt_command(mock_coordinator, mock_mqtt_client):
    """Test that turn_on sends MQTT Modbus write command."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    await switch.async_turn_on()

    mock_mqtt_client.send_command.assert_called_once_with(
        "AC300", "FAKESERIAL001", AC_SWITCH, SWITCH_ON
    )


@pytest.mark.asyncio
async def test_turn_off_sends_mqtt_command(mock_coordinator, mock_mqtt_client):
    """Test that turn_off sends MQTT Modbus write command."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dc_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    await switch.async_turn_off()

    mock_mqtt_client.send_command.assert_called_once_with(
        "AC300", "FAKESERIAL001", DC_SWITCH, SWITCH_OFF
    )


@pytest.mark.asyncio
async def test_turn_on_optimistic_update(mock_coordinator, mock_mqtt_client):
    """Test that turn_on sets optimistic state immediately."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "dc_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    assert switch.is_on is False
    await switch.async_turn_on()

    # Optimistic update should set _attr_is_on before HA state write
    assert switch._attr_is_on is True
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_turn_off_optimistic_update(mock_coordinator, mock_mqtt_client):
    """Test that turn_off sets optimistic state immediately."""
    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    assert switch.is_on is True
    await switch.async_turn_off()

    assert switch._attr_is_on is False
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_command_fails_when_mqtt_disconnected(mock_coordinator):
    """Test that command raises when MQTT is not connected."""
    mock_coordinator.mqtt_client = None

    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    with pytest.raises(BluettiMqttError, match="not connected"):
        await switch.async_turn_on()


@pytest.mark.asyncio
async def test_command_fails_when_mqtt_client_not_connected(mock_coordinator, mock_mqtt_client):
    """Test that command raises when MQTT client exists but is disconnected."""
    mock_mqtt_client.is_connected = False

    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    with pytest.raises(BluettiMqttError, match="not connected"):
        await switch.async_turn_on()


@pytest.mark.asyncio
async def test_command_propagates_mqtt_error(mock_coordinator, mock_mqtt_client):
    """Test that MQTT send_command errors propagate to caller."""
    mock_mqtt_client.send_command.side_effect = BluettiMqttError("publish failed")

    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    with pytest.raises(BluettiMqttError, match="publish failed"):
        await switch.async_turn_on()


@pytest.mark.asyncio
async def test_command_skips_when_missing_model(mock_coordinator, mock_mqtt_client):
    """Test that command is skipped when device_type is empty."""
    mock_coordinator.data["AC300FAKESERIAL001"]["device_type"] = ""

    desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "ac_switch")
    switch = BluettiCloudSwitch(mock_coordinator, "AC300FAKESERIAL001", desc)
    switch.async_write_ha_state = MagicMock()

    await switch.async_turn_on()

    mock_mqtt_client.send_command.assert_not_called()


def test_switch_descriptions_have_registers():
    """Verify all switch descriptions have register addresses and values."""
    for desc in SWITCH_DESCRIPTIONS:
        assert desc.register > 0
        assert desc.data_key
        assert desc.key
        assert desc.on_value is not None
        assert desc.off_value is not None
