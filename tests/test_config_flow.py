"""Tests for the Bluetti Cloud config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bluetti_cloud.const import DOMAIN


@pytest.fixture
def mock_client():
    """Create a mock BluettiCloudApi."""
    client = AsyncMock()
    client.login = AsyncMock()
    client.get_devices = AsyncMock(
        return_value=[
            {
                "deviceSn": "AC300FAKESERIAL001",
                "deviceName": "Winenne",
                "productName": "AC300",
                "deviceType": "AC300",
                "online": True,
            },
        ]
    )
    return client


@pytest.mark.asyncio
async def test_login_transforms_to_device_step(mock_client):
    """Test that successful login proceeds to device selection."""
    with patch(
        "custom_components.bluetti_cloud.config_flow.BluettiCloudApi",
        return_value=mock_client,
    ), patch(
        "custom_components.bluetti_cloud.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        from custom_components.bluetti_cloud.config_flow import BluettiCloudConfigFlow

        flow = BluettiCloudConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_user(
            {"username": "test@example.com", "password": "password123"}
        )

        assert result["type"] == "form"
        assert result["step_id"] == "devices"
        mock_client.login.assert_called_once_with("test@example.com", "password123")
        mock_client.get_devices.assert_called_once()


@pytest.mark.asyncio
async def test_login_auth_error(mock_client):
    """Test that auth errors show on the form."""
    from custom_components.bluetti_cloud.api.client import AuthenticationError

    mock_client.login.side_effect = AuthenticationError("bad creds")

    with patch(
        "custom_components.bluetti_cloud.config_flow.BluettiCloudApi",
        return_value=mock_client,
    ), patch(
        "custom_components.bluetti_cloud.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        from custom_components.bluetti_cloud.config_flow import BluettiCloudConfigFlow

        flow = BluettiCloudConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_user(
            {"username": "test@example.com", "password": "wrong"}
        )

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_login_no_devices(mock_client):
    """Test that empty device list shows error."""
    mock_client.get_devices.return_value = []

    with patch(
        "custom_components.bluetti_cloud.config_flow.BluettiCloudApi",
        return_value=mock_client,
    ), patch(
        "custom_components.bluetti_cloud.config_flow.async_get_clientsession",
        return_value=MagicMock(),
    ):
        from custom_components.bluetti_cloud.config_flow import BluettiCloudConfigFlow

        flow = BluettiCloudConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()

        result = await flow.async_step_user(
            {"username": "test@example.com", "password": "password123"}
        )

        assert result["type"] == "form"
        assert result["errors"] == {"base": "no_devices"}


@pytest.mark.asyncio
async def test_device_selection_creates_entry():
    """Test that selecting devices creates a config entry."""
    from custom_components.bluetti_cloud.config_flow import BluettiCloudConfigFlow

    flow = BluettiCloudConfigFlow()
    flow.hass = MagicMock()
    flow._username = "test@example.com"
    flow._password = "password123"
    flow._devices = [
        {
            "deviceSn": "AC300FAKESERIAL001",
            "deviceName": "Winenne",
            "productName": "AC300",
        },
        {
            "deviceSn": "AC2001234567890",
            "deviceName": "Backup",
            "productName": "AC200",
        },
    ]

    result = await flow.async_step_devices(
        {"devices": ["AC300FAKESERIAL001"]}
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Bluetti (test@example.com)"
    assert result["data"]["username"] == "test@example.com"
    assert result["data"]["devices"] == ["AC300FAKESERIAL001"]
    assert "AC300FAKESERIAL001" in result["data"]["device_info"]
    assert result["data"]["device_info"]["AC300FAKESERIAL001"]["name"] == "Winenne"
    assert result["data"]["device_info"]["AC300FAKESERIAL001"]["model"] == "AC300"
