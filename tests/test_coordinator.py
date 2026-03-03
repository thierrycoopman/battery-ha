"""Tests for the Bluetti Cloud data coordinator."""

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

    mock_api_client.get_device_last_alive.assert_called_once_with("AC300FAKESERIAL001")


@pytest.mark.asyncio
async def test_update_skips_telemetry_for_offline_device(
    mock_hass, mock_config_entry, mock_api_client, device_info
):
    """Offline devices should not trigger getDeviceLastAlive."""
    mock_api_client.get_devices.return_value = [
        {
            "sn": "AC300FAKESERIAL001",
            "name": "Winenne",
            "model": "AC300",
            "sessionState": "Offline",
            "lastAlive": None,
        }
    ]

    coordinator = _make_coordinator(
        mock_hass, mock_config_entry, mock_api_client, ["AC300FAKESERIAL001"], device_info
    )

    data = await coordinator._async_update_data()

    assert data["AC300FAKESERIAL001"]["online"] is False
    mock_api_client.get_device_last_alive.assert_not_called()


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
