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


def test_device_never_seen_is_unreachable():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    assert is_device_reachable({}) is False


def test_boundary_is_inclusive_of_recent_data():
    from custom_components.bluetti_cloud.coordinator import is_device_reachable

    just_inside = time.time() - (DEVICE_STALE_AFTER - 5)
    assert is_device_reachable({"last_seen": just_inside}) is True
