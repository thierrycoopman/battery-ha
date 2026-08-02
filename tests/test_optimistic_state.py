"""A toggled/typed value must hold until the device confirms it.

Writing only to _attr_* is not enough: the entity properties read device_data,
which still holds the pre-write value, so the UI snaps back within a second and
the change looks like it didn't register.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE


def _coordinator(initial: dict):
    coordinator = MagicMock()
    coordinator.data = {"SN": dict(initial)}
    coordinator._device_info = {}
    coordinator.profile_for.return_value = AP300_PROFILE
    coordinator.mqtt_client = MagicMock(is_connected=True)
    return coordinator


@pytest.mark.asyncio
async def test_eco_switch_holds_new_state_until_device_confirms():
    from custom_components.bluetti_cloud.switch import (
        ECO_SWITCH_DESCRIPTIONS,
        BluettiCloudSwitch,
    )

    coordinator = _coordinator({
        "device_type": "AP300", "sub_sn": "X", "ac_eco": False,
    })
    desc = next(d for d in ECO_SWITCH_DESCRIPTIONS if d.key == "ac_eco")
    switch = BluettiCloudSwitch(coordinator, "SN", desc)
    switch.async_write_ha_state = MagicMock()

    assert switch.is_on is False
    await switch.async_turn_on()
    # Must read back as ON even though the device hasn't reported it yet.
    assert switch.is_on is True


@pytest.mark.asyncio
async def test_number_holds_new_value_until_device_confirms():
    from custom_components.bluetti_cloud.number import (
        ECO_NUMBER_DESCRIPTIONS,
        BluettiCloudNumber,
    )

    coordinator = _coordinator({
        "device_type": "AP300", "sub_sn": "X", "ac_eco_power": 10,
    })
    desc = next(d for d in ECO_NUMBER_DESCRIPTIONS if d.key == "ac_eco_power")
    number = BluettiCloudNumber(coordinator, "SN", desc)
    number.async_write_ha_state = MagicMock()

    assert number.native_value == 10
    await number.async_set_native_value(30)
    assert number.native_value == 30


@pytest.mark.asyncio
async def test_select_holds_new_option_until_device_confirms():
    from custom_components.bluetti_cloud.select import (
        CHARGING_MODE_DESCRIPTION,
        BluettiChargingModeSelect,
    )

    coordinator = _coordinator({
        "device_type": "AP300", "sub_sn": "X", "charging_mode_setting": "standard",
    })
    select = BluettiChargingModeSelect(coordinator, "SN", CHARGING_MODE_DESCRIPTION)
    select.async_write_ha_state = MagicMock()

    assert select.current_option == "standard"
    await select.async_select_option("turbo")
    assert select.current_option == "turbo"
