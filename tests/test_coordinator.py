"""Tests for the Bluetti Cloud data coordinator (MQTT+REST hybrid)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bluetti_cloud.api.client import BluettiCloudApiError
from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator


@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.loop = AsyncMock()
    return hass


@pytest.fixture
def mock_api_client(sample_devices_response, sample_last_alive_response):
    client = AsyncMock()
    client.get_devices = AsyncMock(
        return_value=sample_devices_response["data"]
    )
    client.get_device_last_alive = AsyncMock(
        return_value=sample_last_alive_response["data"]
    )
    client.get_energy_detail = AsyncMock(
        return_value={"day": 3.5, "month": 45.2, "year": 320.0, "total": 1234.5}
    )
    return client


@pytest.fixture
def device_sns():
    return ["AC300FAKESERIAL001"]


@pytest.fixture
def device_info():
    return {
        "AC300FAKESERIAL001": {"name": "Winenne", "model": "AC300"},
    }


def _make_coordinator(mock_hass, mock_config_entry, mock_api_client, device_sns, device_info):
    """Create a coordinator with HA internals properly mocked."""
    with patch("homeassistant.helpers.frame.report_usage"):
        return BluettiCloudCoordinator(
            mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
        )


@pytest.mark.asyncio
async def test_update_fetches_devices_and_telemetry(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    data = await coordinator._async_update_data()

    assert "AC300FAKESERIAL001" in data
    device = data["AC300FAKESERIAL001"]
    assert device["online"] is True
    assert device["battery_soc"] == 100
    assert device["power_pv_in"] == 150
    assert device["power_ac_out"] == 200
    assert device["device_name"] == "Winenne"
    assert device["device_type"] == "AC300"
    assert device["ac_switch"] is True
    assert device["dc_switch"] is False

    mock_api_client.get_device_last_alive.assert_called_once_with("AC300FAKESERIAL001")
    mock_api_client.get_energy_detail.assert_called_once_with("AC300FAKESERIAL001")


@pytest.mark.asyncio
async def test_update_includes_energy_data(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """Test that energy totals are fetched and included."""
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    data = await coordinator._async_update_data()

    device = data["AC300FAKESERIAL001"]
    assert device["energy_day"] == 3.5
    assert device["energy_month"] == 45.2
    assert device["energy_year"] == 320.0
    assert device["energy_total"] == 1234.5


@pytest.mark.asyncio
async def test_update_includes_new_mqtt_fields(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """Test that new MQTT-sourced fields are present (initially None from REST)."""
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    data = await coordinator._async_update_data()

    device = data["AC300FAKESERIAL001"]
    # These fields are None from REST — MQTT fills them
    assert "pack_voltage" in device
    assert "pack_current" in device
    assert "charging_status" in device
    assert "charge_time_remaining" in device
    assert "discharge_time_remaining" in device
    assert "mqtt_active" in device


@pytest.mark.asyncio
async def test_update_handles_missing_device(
    mock_hass, mock_config_entry, mock_api_client, device_info
):
    """A selected device not in API response should appear as offline."""
    mock_api_client.get_devices.return_value = []

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, ["AC300FAKESERIAL001"], device_info
    )

    data = await coordinator._async_update_data()

    assert data["AC300FAKESERIAL001"]["online"] is False
    assert data["AC300FAKESERIAL001"]["battery_soc"] is None


@pytest.mark.asyncio
async def test_update_handles_telemetry_failure(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """If getDeviceLastAlive fails, coordinator should still return data."""
    mock_api_client.get_device_last_alive.side_effect = BluettiCloudApiError("timeout")

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    data = await coordinator._async_update_data()

    # Should still have data from homeDevices (embedded lastAlive)
    assert "AC300FAKESERIAL001" in data
    assert data["AC300FAKESERIAL001"]["online"] is True


@pytest.mark.asyncio
async def test_update_handles_energy_failure(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """If get_energy_detail fails, energy fields should be None."""
    mock_api_client.get_energy_detail.side_effect = BluettiCloudApiError("timeout")

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    data = await coordinator._async_update_data()

    device = data["AC300FAKESERIAL001"]
    assert device["energy_day"] is None
    assert device["energy_total"] is None
    # Other data should still be present
    assert device["battery_soc"] == 100


@pytest.mark.asyncio
async def test_update_raises_on_device_list_failure(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """If get_devices fails entirely, coordinator raises UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_api_client.get_devices.side_effect = BluettiCloudApiError("connection error")

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_update_returns_cached_on_error(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """If get_devices fails after a successful fetch, cached data is returned."""
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    # First successful fetch
    data = await coordinator._async_update_data()
    assert data["AC300FAKESERIAL001"]["battery_soc"] == 100

    # Second fetch fails — should return cached
    mock_api_client.get_devices.side_effect = BluettiCloudApiError("connection error")
    cached = await coordinator._async_update_data()
    assert cached["AC300FAKESERIAL001"]["battery_soc"] == 100


@pytest.mark.asyncio
async def test_mqtt_telemetry_merges_into_data(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """Test that MQTT data overlay is applied on REST refresh."""
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    # Simulate MQTT data arriving
    coordinator._mqtt_data["AC300FAKESERIAL001"] = {
        "battery_soc": 72,
        "pack_voltage": 53.2,
        "mqtt_active": True,
    }

    data = await coordinator._async_update_data()

    device = data["AC300FAKESERIAL001"]
    # MQTT data should override REST
    assert device["battery_soc"] == 72
    assert device["pack_voltage"] == 53.2
    assert device["mqtt_active"] is True
    # REST data should still be present
    assert device["power_pv_in"] == 150


@pytest.mark.asyncio
async def test_mqtt_disconnect_restores_rest_interval(
    mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
):
    """Test that REST interval is restored and reconnection is scheduled when MQTT disconnects."""
    from datetime import timedelta

    from custom_components.bluetti_cloud.const import DEFAULT_SCAN_INTERVAL

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, device_sns, device_info
    )

    # Simulate MQTT was connected, then disconnected
    coordinator._mqtt_connected = True
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected = False
    coordinator._mqtt_client = mock_mqtt

    # Prevent actual reconnect loop coroutine from being created
    with patch.object(coordinator, "_schedule_reconnect") as mock_reconnect:
        await coordinator._async_update_data()

    assert coordinator._mqtt_connected is False
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    # Verify reconnection was scheduled
    mock_reconnect.assert_called_once()


def _load_ap300_fixtures():
    """Load the real AP300 (APEX 300) REST fixtures captured from the device."""
    import json
    import pathlib

    base = pathlib.Path(__file__).parent / "fixtures" / "apex300"
    home = json.loads((base / "home_devices.json").read_text())
    last_alive = json.loads((base / "last_alive.json").read_text())
    return home, last_alive


@pytest.mark.asyncio
async def test_ap300_rest_baseline_maps_voltage_and_charging(
    mock_hass, mock_config_entry
):
    """AP300 REST baseline: voltage and charging status come from REST
    (MQTT overlays these live, but the REST values must be correct too)."""
    home, last_alive = _load_ap300_fixtures()
    sn = home["sn"]

    client = AsyncMock()
    client.get_devices = AsyncMock(return_value=[home])
    client.get_device_last_alive = AsyncMock(return_value=last_alive)
    # AP300 energyDetail returns zeros in practice
    client.get_energy_detail = AsyncMock(
        return_value={"day": 0, "month": 0, "year": 0, "total": 0}
    )

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, client, [sn], {sn: {"name": "APEX", "model": "AP300"}}
    )

    data = await coordinator._async_update_data()
    dev = data[sn]

    # Profile resolved from model + factoryProtocolVer 2015 (MQTT+REST, V2)
    assert coordinator.profile_for(sn).data_path == "mqtt+rest"
    # Online + aggregate battery from REST
    assert dev["online"] is True
    assert dev["battery_soc"] == 95
    # Voltage surfaces via the "Battery Total Voltage" sensor (pack_total_voltage)
    assert dev["pack_total_voltage"] == 531.7  # from batteryVoltage
    assert dev["charging_status"] == "standby"  # packChargingStatus 0
    # Switch states readable (but not controllable)
    assert dev["ac_switch"] is False
    assert dev["dc_switch"] is False
    # iotSession "1" from the API normalizes to "Online"
    assert dev["iot_session"] == "Online"


@pytest.mark.asyncio
async def test_ap300_v2_charging_status_codes(mock_hass, mock_config_entry):
    """AP300 is a V2 device: packChargingStatus 4 (AC charging) must decode."""
    home, last_alive = _load_ap300_fixtures()
    sn = home["sn"]
    # Code 4 = AC charging in the V2 map; the V1 BATTERY_STATE_MAP would miss it.
    last_alive = {**last_alive, "packChargingStatus": "4"}

    client = AsyncMock()
    client.get_devices = AsyncMock(return_value=[home])
    client.get_device_last_alive = AsyncMock(return_value=last_alive)
    client.get_energy_detail = AsyncMock(return_value={})

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, client, [sn], {sn: {"name": "APEX", "model": "AP300"}}
    )

    data = await coordinator._async_update_data()
    assert data[sn]["charging_status"] == "charging"


@pytest.mark.asyncio
async def test_mqtt_active_keeps_fast_interval_when_rest_only_device_present(
    mock_hass, mock_config_entry
):
    """A REST-only device must not be slowed to the MQTT interval by a
    co-configured MQTT device sharing the coordinator."""
    from datetime import timedelta

    from custom_components.bluetti_cloud.api.profiles import (
        AC300_PROFILE,
        DeviceProfile,
    )
    from custom_components.bluetti_cloud.const import (
        DEFAULT_SCAN_INTERVAL,
        MQTT_SCAN_INTERVAL,
    )

    rest_only_profile = DeviceProfile(
        model="RESTONLY", protocol_ver_min=0, data_path="rest_only"
    )
    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, AsyncMock(), ["AC300X", "RESTY"], {}
    )
    # Simulate a completed REST refresh: data + resolved profiles present.
    coordinator._mqtt.overlays.clear()
    coordinator.data = {
        "AC300X": {"device_type": "AC300", "sub_sn": "X"},
        "RESTY": {"device_type": "RESTONLY", "sub_sn": "Y"},
    }
    coordinator._profiles = {"AC300X": AC300_PROFILE, "RESTY": rest_only_profile}

    # Make the executor + MQTT client no-ops so async_start reaches the
    # interval decision without real network work.
    mock_hass.async_add_executor_job = AsyncMock()
    fake_client = MagicMock()
    fake_client.is_connected = False
    fake_client.async_prepare = AsyncMock(return_value={})
    with patch(
        "custom_components.bluetti_cloud.mqtt_manager.BluettiMqttClient",
        return_value=fake_client,
    ):
        await coordinator.async_start_mqtt()

    # Mixed config with a rest_only device → keep the fast 30s interval.
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    assert DEFAULT_SCAN_INTERVAL < MQTT_SCAN_INTERVAL
