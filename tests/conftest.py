"""Shared test fixtures for Bluetti Cloud tests."""

import pytest


@pytest.fixture
def sample_login_response():
    """Successful login response from Bluetti API."""
    return {
        "data": {
            "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.fake_token",
            "refresh": "abc123refresh",
            "ttl": "2678400",
        },
        "msgCode": 0,
        "message": "OK",
    }


@pytest.fixture
def sample_login_failure():
    """Failed login response."""
    return {
        "data": None,
        "msgCode": 1,
        "message": "Invalid credentials",
    }


@pytest.fixture
def sample_devices_response():
    """homeDevices endpoint response with one device group."""
    return {
        "msgCode": 0,
        "message": "OK",
        "data": [
            {
                "groupId": 1,
                "groupName": "Home",
                "deviceList": [
                    {
                        "deviceSn": "AC300FAKESERIAL001",
                        "deviceName": "Winenne",
                        "productName": "AC300",
                        "deviceType": "AC300",
                        "online": True,
                        "lastAlive": {
                            "batterySoc": 100,
                            "powerPvIn": 0,
                            "powerGridIn": 0,
                            "powerAcOut": 0,
                            "powerDcOut": 0,
                        },
                    },
                    {
                        "deviceSn": "AC2001234567890",
                        "deviceName": "Backup",
                        "productName": "AC200",
                        "deviceType": "AC200",
                        "online": False,
                        "lastAlive": None,
                    },
                ],
            }
        ],
    }


@pytest.fixture
def sample_last_alive_response():
    """getDeviceLastAlive endpoint response."""
    return {
        "msgCode": 0,
        "message": "OK",
        "data": {
            "deviceSn": "AC300FAKESERIAL001",
            "timestamp": 1709510400000,
            "batterySoc": 100,
            "totalBatteryPercent": 100,
            "powerPvIn": 150,
            "powerGridIn": 0,
            "powerAcOut": 200,
            "powerDcOut": 50,
            "acSwitch": 1,
            "dcSwitch": 0,
            "gridChargeOn": 0,
            "pvChargeOn": 1,
        },
    }


@pytest.fixture
def sample_fulfillment_response():
    """fulfillment endpoint response."""
    return {
        "msgCode": 0,
        "message": "OK",
        "data": True,
    }
