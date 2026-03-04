"""Tests for Bluetti Cloud sensor and binary sensor platforms."""

from unittest.mock import MagicMock

import pytest

from custom_components.bluetti_cloud.sensor import (
    SENSOR_DESCRIPTIONS,
    BluettiCloudSensor,
)
from custom_components.bluetti_cloud.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    BluettiCloudBinarySensor,
)
from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator


@pytest.fixture
def coordinator_data():
    return {
        "AC300FAKESERIAL001": {
            "online": True,
            "iot_session": "Online",
            "device_name": "Winenne",
            "device_type": "AC300",
            "sub_sn": "FAKESERIAL001",
            "battery_soc": 85,
            "pack_voltage": 53.2,
            "pack_current": -1.5,
            "charging_status": "discharging",
            "charge_time_remaining": 0,
            "discharge_time_remaining": 120,
            "pack_count": 1,
            "inverter_count": 1,
            "power_pv_in": 250,
            "power_grid_in": 0,
            "power_ac_out": 150,
            "power_dc_out": 30,
            "power_feed_back": 0,
            "ac_switch": True,
            "dc_switch": False,
            "pv_switch": None,
            "grid_switch": None,
            "energy_day": 3.5,
            "energy_month": 45.2,
            "energy_year": 320.0,
            "energy_total": 1234.5,
            "last_update": "2026-03-04 10:00:00",
            "mqtt_active": True,
        }
    }


@pytest.fixture
def mock_coordinator(coordinator_data):
    coordinator = MagicMock(spec=BluettiCloudCoordinator)
    coordinator.data = coordinator_data
    coordinator._device_info = {"AC300FAKESERIAL001": {"name": "Winenne", "model": "AC300"}}
    return coordinator


def test_sensor_battery_soc(mock_coordinator):
    """Test battery SOC sensor returns correct value."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "battery_soc")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 85
    assert sensor.unique_id == "AC300FAKESERIAL001_battery_soc"


def test_sensor_pv_input(mock_coordinator):
    """Test PV input sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "power_pv_in")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 250


def test_sensor_pack_voltage(mock_coordinator):
    """Test MQTT-sourced pack voltage sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "pack_voltage")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 53.2


def test_sensor_pack_current(mock_coordinator):
    """Test MQTT-sourced pack current sensor (negative = discharging)."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "pack_current")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == -1.5


def test_sensor_charging_status(mock_coordinator):
    """Test MQTT-sourced charging status sensor (string value)."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "charging_status")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == "discharging"


def test_sensor_charge_time_remaining(mock_coordinator):
    """Test charge time remaining sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "charge_time_remaining")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 0


def test_sensor_discharge_time_remaining(mock_coordinator):
    """Test discharge time remaining sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "discharge_time_remaining")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 120


def test_sensor_energy_day(mock_coordinator):
    """Test energy today sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "energy_day")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 3.5


def test_sensor_energy_total(mock_coordinator):
    """Test lifetime energy sensor."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "energy_total")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 1234.5


def test_sensor_returns_none_when_no_data(mock_coordinator):
    """Test sensor returns None for missing device."""
    desc = SENSOR_DESCRIPTIONS[0]
    sensor = BluettiCloudSensor(mock_coordinator, "UNKNOWN_SN", desc)

    assert sensor.native_value is None


def test_all_sensor_descriptions_have_required_fields():
    """Verify all sensor descriptions have essential attributes."""
    for desc in SENSOR_DESCRIPTIONS:
        assert desc.key, f"Missing key on sensor description"
        assert desc.data_key, f"Missing data_key on {desc.key}"
        assert desc.name, f"Missing name on {desc.key}"
        # charging_status has no device_class or unit (it's a string sensor)
        # so we only check key, data_key, name


def test_sensor_descriptions_with_units_have_device_class():
    """Sensors with units should have a device_class for proper HA rendering."""
    for desc in SENSOR_DESCRIPTIONS:
        if desc.native_unit_of_measurement is not None:
            assert desc.device_class is not None, (
                f"Sensor {desc.key} has a unit but no device_class"
            )


def test_binary_sensor_online(mock_coordinator):
    """Test online binary sensor."""
    desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "online")
    sensor = BluettiCloudBinarySensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.is_on is True
    assert sensor.unique_id == "AC300FAKESERIAL001_online"


def test_binary_sensor_offline(mock_coordinator):
    """Test offline binary sensor."""
    mock_coordinator.data["AC300FAKESERIAL001"]["online"] = False
    desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "online")
    sensor = BluettiCloudBinarySensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.is_on is False


def test_binary_sensor_iot_session(mock_coordinator):
    """Test IoT session binary sensor."""
    desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "iot_session")
    sensor = BluettiCloudBinarySensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.is_on is True  # "Online" matches on_value


def test_binary_sensor_iot_session_offline(mock_coordinator):
    """Test IoT session binary sensor when offline."""
    mock_coordinator.data["AC300FAKESERIAL001"]["iot_session"] = "Offline"
    desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "iot_session")
    sensor = BluettiCloudBinarySensor(mock_coordinator, "AC300FAKESERIAL001", desc)

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
