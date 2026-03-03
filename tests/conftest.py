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
    """homeDevices endpoint response — flat list of devices."""
    return {
        "msgCode": 0,
        "message": "OK",
        "data": [
            {
                "sn": "AC300FAKESERIAL001",
                "name": "Winenne",
                "model": "AC300",
                "sessionState": "Online",
                "batSOC": "97",
                "powerPvIn": 0,
                "powerGridIn": 0,
                "powerAcOut": 0,
                "powerDcOut": 0,
                "lastAlive": {
                    "batterySoc": "100",
                    "powerPvIn": "0",
                    "powerGridIn": "0",
                    "powerAcOut": "0",
                    "powerDcOut": "0",
                    "acSwitch": "0",
                    "dcSwitch": "1",
                },
            },
            {
                "sn": "AC200FAKESERIAL002",
                "name": "Backup",
                "model": "AC200",
                "sessionState": "Offline",
                "batSOC": "50",
                "lastAlive": None,
            },
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
            "timestamp": "2026-03-03 20:49:00",
            "batterySoc": "100",
            "powerPvIn": "150",
            "powerGridIn": "0",
            "powerAcOut": "200",
            "powerDcOut": "50",
            "acSwitch": "1",
            "dcSwitch": "0",
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
