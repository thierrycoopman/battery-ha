"""Tests for Bluetti Cloud sensor and binary sensor platforms."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bluetti_cloud.sensor import (
    SENSOR_DESCRIPTIONS,
    BluettiCloudSensor,
)
from custom_components.bluetti_cloud.binary_sensor import BluettiCloudOnlineSensor
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
    return coordinator


def test_sensor_native_value(mock_coordinator):
    """Test that sensor returns correct value from coordinator data."""
    desc = SENSOR_DESCRIPTIONS[0]  # battery_soc
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 85
    assert sensor.unique_id == "AC300FAKESERIAL001_battery_soc"


def test_sensor_pv_input(mock_coordinator):
    """Test PV input sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "power_pv_in")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 250


def test_sensor_returns_none_when_no_data(mock_coordinator):
    """Test sensor returns None for missing device."""
    desc = SENSOR_DESCRIPTIONS[0]
    sensor = BluettiCloudSensor(mock_coordinator, "UNKNOWN_SN", desc)

    assert sensor.native_value is None


def test_all_sensor_descriptions_have_required_fields():
    """Verify all sensor descriptions have required attributes."""
    for desc in SENSOR_DESCRIPTIONS:
        assert desc.key
        assert desc.data_key
        assert desc.device_class is not None
        assert desc.native_unit_of_measurement is not None
        assert desc.name


def test_binary_sensor_online(mock_coordinator):
    """Test online binary sensor."""
    sensor = BluettiCloudOnlineSensor(mock_coordinator, "AC300FAKESERIAL001")

    assert sensor.is_on is True
    assert sensor.unique_id == "AC300FAKESERIAL001_online"


def test_binary_sensor_offline(mock_coordinator):
    """Test offline binary sensor."""
    mock_coordinator.data["AC300FAKESERIAL001"]["online"] = False
    sensor = BluettiCloudOnlineSensor(mock_coordinator, "AC300FAKESERIAL001")

    assert sensor.is_on is False


def test_sensor_device_info(mock_coordinator):
    """Test device_info is correctly set from coordinator data."""
    desc = SENSOR_DESCRIPTIONS[0]
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    device_info = sensor.device_info
    assert device_info is not None
    assert ("bluetti_cloud", "AC300FAKESERIAL001") in device_info["identifiers"]
    assert device_info["manufacturer"] == "Bluetti"
    assert device_info["name"] == "Winenne"
    assert device_info["model"] == "AC300"
