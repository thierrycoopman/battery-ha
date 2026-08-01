"""Tests for Bluetti Cloud sensor and binary sensor platforms."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.bluetti_cloud.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    BluettiCloudBinarySensor,
)
from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator
from custom_components.bluetti_cloud.sensor import (
    PACK_SUMMARY_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    BluettiCloudSensor,
)


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
            "charging_status": "discharging",
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
            # FC=16 aggregate battery data
            "pack_total_voltage": 54.0,
            "pack_total_current": 6.5,
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


def test_sensor_battery_total_voltage(mock_coordinator):
    """Test battery total voltage sensor (aggregate from FC=16 regs 92-93)."""
    desc = next(d for d in PACK_SUMMARY_DESCRIPTIONS if d.key == "pack_total_voltage")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 54.0


def test_sensor_battery_total_current(mock_coordinator):
    """Test battery total current sensor (aggregate from FC=16 regs 92-93)."""
    desc = next(d for d in PACK_SUMMARY_DESCRIPTIONS if d.key == "pack_total_current")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == 6.5


def test_sensor_charging_status(mock_coordinator):
    """Test MQTT-sourced charging status sensor (string value)."""
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "charging_status")
    sensor = BluettiCloudSensor(mock_coordinator, "AC300FAKESERIAL001", desc)

    assert sensor.native_value == "discharging"


def test_sensor_pack_summary_no_soh_or_temp(mock_coordinator):
    """Verify PACK_SUMMARY_DESCRIPTIONS does not include unavailable AC300 fields."""
    keys = {d.key for d in PACK_SUMMARY_DESCRIPTIONS}
    # SOH, temp, charge/discharge times are not available from AC300 FC=16
    assert "pack_total_soh" not in keys
    assert "pack_average_temp" not in keys
    assert "charge_full_time" not in keys
    assert "discharge_empty_time" not in keys


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
        assert desc.key, "Missing key on sensor description"
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


@pytest.mark.asyncio
async def test_rest_only_summary_sensor_is_voltage_only():
    """A REST-only device gets Battery Total Voltage but not Total Current
    (REST has no aggregate current field)."""
    from custom_components.bluetti_cloud.api.profiles import DeviceProfile
    from custom_components.bluetti_cloud.sensor import async_setup_entry

    rest_only = DeviceProfile(
        model="RESTONLY", protocol_ver_min=0, data_path="rest_only"
    )
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator._device_info = {}
    coordinator.get_pack_count.return_value = 0
    coordinator.profile_for.return_value = rest_only

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["RESTSN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    summary_keys = {
        e.entity_description.data_key
        for e in added
        if e.entity_description.data_key in ("pack_total_voltage", "pack_total_current")
    }
    assert "pack_total_voltage" in summary_keys
    assert "pack_total_current" not in summary_keys


@pytest.mark.asyncio
async def test_per_battery_node_soc_sensor():
    """Battery sub-device nodes get their own SOC sensor."""
    from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
    from custom_components.bluetti_cloud.sensor import (
        BluettiCloudNodeBatterySensor,
        async_setup_entry,
    )

    nodes = [
        {"slave_addr": 11, "model": 3007, "model_name": "D1 Hub (HD1)",
         "is_battery": False, "online": True},
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True, "pack_soc": 95, "cell_count": 16},
    ]
    coordinator = MagicMock()
    coordinator.data = {"SN": {"nodes": nodes}}
    coordinator._device_info = {}
    coordinator.get_pack_count.return_value = 0
    coordinator.profile_for.return_value = AP300_PROFILE
    coordinator.get_nodes.return_value = nodes

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["SN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    node_sensors = [e for e in added if isinstance(e, BluettiCloudNodeBatterySensor)]
    # Only the battery node gets a SOC sensor, not the hub
    assert len(node_sensors) == 1
    assert node_sensors[0]._slave_addr == 51
    assert node_sensors[0].native_value == 95
    assert "B300" in node_sensors[0].name
