"""Energy totals must not be reported as zero when the source has no data.

This device's REST energy endpoint returns all zeros, and its lifetime
charge/discharge counters are identical to each other — neither is a usable
accumulator. Publishing 0 kWh would read as "never produced any energy", which
is worse than reporting nothing; the MQTT energy sensors carry the real values.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator


def _coordinator(energy):
    client = AsyncMock()
    client.get_devices = AsyncMock(return_value=[{
        "sn": "SN", "subSn": "X", "name": "APEX", "model": "AP300",
        "sessionState": "Online", "factoryProtocolVer": "2015",
        "lastAlive": {"batterySoc": "91"},
    }])
    client.get_device_last_alive = AsyncMock(return_value={
        "allFieldIsNull": False, "batterySoc": "91",
    })
    client.get_energy_detail = AsyncMock(return_value=energy)
    hass = MagicMock()
    entry = MagicMock()
    with patch("homeassistant.helpers.frame.report_usage"):
        return BluettiCloudCoordinator(
            hass, entry, client, ["SN"], {"SN": {"name": "APEX", "model": "AP300"}}
        )


@pytest.mark.asyncio
async def test_all_zero_energy_is_reported_as_unknown():
    coord = _coordinator({"day": 0, "month": 0, "year": 0, "total": 0})
    data = await coord._async_update_data()
    for key in ("energy_day", "energy_month", "energy_year", "energy_total"):
        assert data["SN"][key] is None, f"{key} should be unknown, not 0"


@pytest.mark.asyncio
async def test_real_energy_values_are_kept():
    coord = _coordinator({"day": 3.5, "month": 45.2, "year": 320.0, "total": 1234.5})
    data = await coord._async_update_data()
    assert data["SN"]["energy_day"] == 3.5
    assert data["SN"]["energy_total"] == 1234.5


@pytest.mark.asyncio
async def test_a_genuine_zero_day_is_kept_when_other_totals_are_real():
    """Zero today with a real lifetime total is a legitimate reading."""
    coord = _coordinator({"day": 0, "month": 12.0, "year": 300.0, "total": 900.0})
    data = await coord._async_update_data()
    assert data["SN"]["energy_day"] == 0
    assert data["SN"]["energy_total"] == 900.0
