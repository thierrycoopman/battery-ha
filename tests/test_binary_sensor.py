"""Tests for the Bluetti Cloud binary sensor platform."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.bluetti_cloud.api.profiles import AC300_PROFILE, AP300_PROFILE
from custom_components.bluetti_cloud.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    OUTPUT_STATE_DESCRIPTIONS,
    async_setup_entry,
)


def _coordinator():
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator._device_info = {}
    coordinator.profile_for.side_effect = (
        lambda sn: AC300_PROFILE if "AC300" in sn else AP300_PROFILE
    )
    return coordinator


@pytest.mark.asyncio
async def test_rest_only_device_gets_output_state_sensors():
    """AP300 (rest_only) gets base sensors + read-only output-state sensors."""
    coordinator = _coordinator()
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["AP300SN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    assert len(added) == len(BINARY_SENSOR_DESCRIPTIONS) + len(OUTPUT_STATE_DESCRIPTIONS)
    keys = {e.entity_description.key for e in added}
    assert "ac_output_state" in keys
    assert "dc_output_state" in keys


@pytest.mark.asyncio
async def test_mqtt_device_gets_no_output_state_sensors():
    """AC300 (mqtt+rest) gets only the base binary sensors (it has switches)."""
    coordinator = _coordinator()
    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.data = {"devices": ["AC300SN"]}

    added: list = []
    with patch("homeassistant.helpers.frame.report_usage"):
        await async_setup_entry(MagicMock(), entry, added.extend)

    assert len(added) == len(BINARY_SENSOR_DESCRIPTIONS)
    keys = {e.entity_description.key for e in added}
    assert "ac_output_state" not in keys
