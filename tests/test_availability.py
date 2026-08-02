"""Device reachability and staleness.

The cloud API has no reliable power-state signal: the V2 ctrl power bit reads 0
on a device that is demonstrably powered on, and REST `sessionState` reports
Offline for an AC300 whose MQTT link works fine. What can be determined is
whether the device has been heard from recently, which is what decides if its
readings are still meaningful.
"""

import time
from unittest.mock import MagicMock

from custom_components.bluetti_cloud.const import DEVICE_STALE_AFTER


def _coordinator_with(last_seen):
    from custom_components.bluetti_cloud.coordinator import BluettiCloudCoordinator

    coord = MagicMock(spec=BluettiCloudCoordinator)
    coord.data = {"SN": {"last_seen": last_seen}}
    coord.last_update_success = True
    return coord


def test_recently_seen_device_is_reachable():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    assert is_device_reachable({"last_seen": time.time()}) is True


def test_device_not_heard_from_is_unreachable():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    stale = time.time() - (DEVICE_STALE_AFTER + 60)
    assert is_device_reachable({"last_seen": stale}) is False


def test_never_seen_does_not_hide_entities():
    """Superseded by test_device_never_seen_stays_available (kept explicit)."""
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    assert is_device_reachable({}) is True


def test_boundary_is_inclusive_of_recent_data():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    just_inside = time.time() - (DEVICE_STALE_AFTER - 5)
    assert is_device_reachable({"last_seen": just_inside}) is True


def test_entities_go_unavailable_when_device_is_stale():
    """Stale readings must not be presented as current."""
    from custom_components.bluetti_cloud.sensor import (
        SENSOR_DESCRIPTIONS,
        BluettiCloudSensor,
    )

    coord = MagicMock()
    coord.last_update_success = True
    coord._device_info = {}
    coord.data = {"SN": {"battery_soc": 94, "last_seen": time.time()}}
    desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "battery_soc")
    sensor = BluettiCloudSensor(coord, "SN", desc)
    assert sensor.available is True

    coord.data["SN"]["last_seen"] = time.time() - (DEVICE_STALE_AFTER + 60)
    assert sensor.available is False


def test_reachable_sensor_stays_available_to_report_unreachable():
    """The reachability sensor itself must not disappear when the device does."""
    from custom_components.bluetti_cloud.binary_sensor import (
        REACHABLE_DESCRIPTION,
        BluettiReachableBinarySensor,
    )

    coord = MagicMock()
    coord.last_update_success = True
    coord._device_info = {}
    coord.data = {"SN": {"last_seen": time.time() - (DEVICE_STALE_AFTER + 60)}}
    sensor = BluettiReachableBinarySensor(coord, "SN", REACHABLE_DESCRIPTION)
    assert sensor.available is True
    assert sensor.is_on is False


def test_device_never_seen_stays_available():
    """Absence of a timestamp is not evidence of unreachability.

    A device we have never established contact time for (e.g. an AC300 whose
    REST telemetry is all-null and whose MQTT link is down) must not have all
    its entities hidden — that regressed working setups. Only a device that was
    seen and then went quiet is treated as unreachable.
    """
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    assert is_device_reachable({}) is True
    assert is_device_reachable({"last_seen": None}) is True


def test_device_seen_then_gone_quiet_is_unreachable():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    stale = time.time() - (DEVICE_STALE_AFTER + 60)
    assert is_device_reachable({"last_seen": stale}) is False


def test_reachable_sensor_is_unknown_without_a_contact_time():
    """Reporting "reachable" for a device we've never heard from would be a
    claim we cannot support."""
    from custom_components.bluetti_cloud.binary_sensor import (
        REACHABLE_DESCRIPTION,
        BluettiReachableBinarySensor,
    )

    coord = MagicMock()
    coord.last_update_success = True
    coord._device_info = {}
    coord.data = {"SN": {}}
    sensor = BluettiReachableBinarySensor(coord, "SN", REACHABLE_DESCRIPTION)
    assert sensor.is_on is None
