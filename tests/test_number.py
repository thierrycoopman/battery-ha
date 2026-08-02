"""Tests for the ECO parameter number entities."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE, AP300_PROFILE
from custom_components.bluetti_cloud.number import (
    ECO_NUMBER_DESCRIPTIONS,
    async_setup_entry,
)


def _entry(profile):
    coordinator = MagicMock()
    coordinator.data = {"SN": {}}
    coordinator._device_info = {}
    coordinator.profile_for.return_value = profile
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["SN"]}
    return entry


@pytest.mark.asyncio
async def test_eco_numbers_created_for_eco_capable_device():
    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), _entry(AP300_PROFILE), added.extend)
    assert len(added) == len(ECO_NUMBER_DESCRIPTIONS) == 4


@pytest.mark.asyncio
async def test_no_eco_numbers_for_device_without_eco():
    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), _entry(AC300_PROFILE), added.extend)
    assert added == []


@pytest.mark.asyncio
async def test_number_bounds_come_from_device_ranges():
    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), _entry(AP300_PROFILE), added.extend)
    by_key = {e.entity_description.key: e for e in added}
    assert by_key["ac_eco_power"].native_min_value == 10
    assert by_key["ac_eco_power"].native_max_value == 40
    assert by_key["dc_eco_power"].native_min_value == 5
    assert by_key["dc_eco_power"].native_max_value == 20
    assert by_key["ac_eco_auto_off"].native_max_value == 4
