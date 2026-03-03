"""Tests for the Bluetti Cloud API client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bluetti_cloud.api.client import (
    AuthenticationError,
    BluettiCloudApi,
)


def _mock_response(data: dict):
    """Create a mock async context manager mimicking aiohttp response."""
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=data)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session with synchronous method returns."""
    session = MagicMock()
    # session.post() and session.request() return context managers directly
    session.post = MagicMock()
    session.request = MagicMock()
    return session


@pytest.mark.asyncio
async def test_login_success(mock_session, sample_login_response):
    mock_session.post.return_value = _mock_response(sample_login_response)

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    assert client.is_authenticated
    assert client._token == sample_login_response["data"]["token"]
    mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_login_failure(mock_session, sample_login_failure):
    mock_session.post.return_value = _mock_response(sample_login_failure)

    client = BluettiCloudApi(mock_session)
    with pytest.raises(AuthenticationError, match="Login failed"):
        await client.login("test@example.com", "wrong_password")

    assert not client.is_authenticated


@pytest.mark.asyncio
async def test_login_sends_transformed_password(mock_session, sample_login_response):
    mock_session.post.return_value = _mock_response(sample_login_response)

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "TestPassword123!")

    call_kwargs = mock_session.post.call_args
    form_data = call_kwargs.kwargs.get("data", {})
    assert form_data["password"] == "FFC121A2210958BF74E5A874668F3D978D24B6A8241496CCFF3C0EA245E4F126"
    assert form_data["passOpen"] == "b890d65b4cad5e88b713c465bda69ec02cff13ed3ea675b79b7944e70d5281cd"


@pytest.mark.asyncio
async def test_get_devices(mock_session, sample_login_response, sample_devices_response):
    mock_session.post.return_value = _mock_response(sample_login_response)
    mock_session.request.return_value = _mock_response(sample_devices_response)

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    devices = await client.get_devices()
    assert len(devices) == 2
    assert devices[0]["deviceSn"] == "AC300FAKESERIAL001"
    assert devices[1]["deviceSn"] == "AC2001234567890"


@pytest.mark.asyncio
async def test_get_device_last_alive(
    mock_session, sample_login_response, sample_last_alive_response
):
    mock_session.post.return_value = _mock_response(sample_login_response)
    mock_session.request.return_value = _mock_response(sample_last_alive_response)

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    data = await client.get_device_last_alive("AC300FAKESERIAL001")
    assert data["batterySoc"] == 100
    assert data["powerPvIn"] == 150


@pytest.mark.asyncio
async def test_control_device(
    mock_session, sample_login_response, sample_fulfillment_response
):
    mock_session.post.return_value = _mock_response(sample_login_response)
    mock_session.request.return_value = _mock_response(sample_fulfillment_response)

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    result = await client.control_device("AC300FAKESERIAL001", "SetCtrlAcSwitch", "1")
    assert result["msgCode"] == 0


@pytest.mark.asyncio
async def test_auto_reauth_on_805(mock_session, sample_login_response):
    """Test that client re-authenticates when it gets a 805 response."""
    expired_response = {"msgCode": 805, "message": "Token expired"}
    success_response = {"msgCode": 0, "data": [{"groupId": 1, "deviceList": []}]}

    mock_session.post.return_value = _mock_response(sample_login_response)
    mock_session.request.side_effect = [
        _mock_response(expired_response),
        _mock_response(success_response),
    ]

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    devices = await client.get_devices()
    assert devices == []
    # Initial login + re-auth after 805
    assert mock_session.post.call_count == 2


@pytest.mark.asyncio
async def test_request_without_auth_raises(mock_session):
    client = BluettiCloudApi(mock_session)
    with pytest.raises(AuthenticationError, match="Not authenticated"):
        await client.get_devices()


@pytest.mark.asyncio
async def test_gateway_routing(mock_session, sample_login_response):
    """Verify bluiotdata calls go to gwpry, blusmartprod to gw."""
    mock_session.post.return_value = _mock_response(sample_login_response)
    mock_session.request.return_value = _mock_response({"msgCode": 0, "data": {}})

    client = BluettiCloudApi(mock_session)
    await client.login("test@example.com", "password123")

    # bluiotdata → gwpry
    await client.get_device_last_alive("SN123")
    call = mock_session.request.call_args
    assert "gwpry.bluettipower.com" in call[0][1]

    # blusmartprod → gw
    mock_session.request.reset_mock()
    mock_session.request.return_value = _mock_response(
        {"msgCode": 0, "data": [{"groupId": 1, "deviceList": []}]}
    )
    await client.get_devices()
    call = mock_session.request.call_args
    assert "gw.bluettipower.com" in call[0][1]
