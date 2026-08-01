"""Tests for the Bluetti Cloud config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Create a mock BluettiCloudApi."""
    client = AsyncMock()
    client.login = AsyncMock()
    client.get_devices = AsyncMock(
        return_value=[
            {
                "sn": "AC300FAKESERIAL001",
                "name": "Winenne",
                "model": "AC300",
                "sessionState": "Online",
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
            "sn": "AC300FAKESERIAL001",
            "name": "Winenne",
            "model": "AC300",
        },
        {
            "sn": "AC2001234567890",
            "name": "Backup",
            "model": "AC200",
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


@pytest.mark.asyncio
async def test_reconfigure_lists_devices_with_current_selection(mock_client):
    """Reconfigure re-authenticates and pre-selects the currently configured devices."""
    mock_client.get_devices = AsyncMock(
        return_value=[
            {"sn": "AC300FAKESERIAL001", "name": "Winenne", "model": "AC300",
             "sessionState": "Online"},
            {"sn": "AP300FAKESERIAL002", "name": "APEX", "model": "AP300",
             "sessionState": "Online"},
        ]
    )
    entry = MagicMock()
    entry.data = {
        "username": "test@example.com",
        "password": "password123",
        "devices": ["AC300FAKESERIAL001"],
        "device_info": {"AC300FAKESERIAL001": {"name": "Winenne", "model": "AC300"}},
    }

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
        flow._get_reconfigure_entry = MagicMock(return_value=entry)

        result = await flow.async_step_reconfigure()

        # Shows the device picker directly — credentials come from the entry
        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"
        mock_client.login.assert_called_once_with("test@example.com", "password123")
        # Both devices offered, including the newly-bound AP300
        assert len(flow._devices) == 2


@pytest.mark.asyncio
async def test_reconfigure_updates_entry_with_new_device(mock_client):
    """Selecting an added device updates the entry and reloads it."""
    mock_client.get_devices = AsyncMock(
        return_value=[
            {"sn": "AC300FAKESERIAL001", "name": "Winenne", "model": "AC300",
             "sessionState": "Online"},
            {"sn": "AP300FAKESERIAL002", "name": "APEX", "model": "AP300",
             "sessionState": "Online"},
        ]
    )
    entry = MagicMock()
    entry.data = {
        "username": "test@example.com",
        "password": "password123",
        "devices": ["AC300FAKESERIAL001"],
        "device_info": {},
    }

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
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_update_reload_and_abort = MagicMock(
            return_value={"type": "abort", "reason": "reconfigure_successful"}
        )

        await flow.async_step_reconfigure()  # populates the device list
        result = await flow.async_step_reconfigure(
            {"devices": ["AC300FAKESERIAL001", "AP300FAKESERIAL002"]}
        )

        assert result["reason"] == "reconfigure_successful"
        kwargs = flow.async_update_reload_and_abort.call_args.kwargs
        new_data = kwargs["data_updates"]
        assert new_data["devices"] == ["AC300FAKESERIAL001", "AP300FAKESERIAL002"]
        # Credentials preserved; device_info rebuilt for both devices
        assert new_data["device_info"]["AP300FAKESERIAL002"]["model"] == "AP300"
