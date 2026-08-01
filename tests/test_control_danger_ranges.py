"""The write guard must refuse destructive registers — by RANGE, not by name.

Some dangerous addresses are bare literals absent from the register map
(e.g. 2440 restore-cert-defaults, 40001 grid auto-test), so a name-based
denylist would miss them.
"""

import pytest

from custom_components.bluetti_cloud.api.modbus import build_switch_payload

# (register, why it must never be writable)
FORBIDDEN = [
    (2006, "irreversibly clears lifetime energy counters"),
    (2013, "system power off — only a physical button recovers"),
    (2206, "factory reset"),
    (2218, "region setting — re-derives grid defaults"),
    (2230, "inverter modbus address — self-inflicted DoS"),
    (2233, "battery aging / deep-discharge calibration"),
    (2408, "disables anti-islanding — LETHAL to line workers"),
    (2440, "restore cert defaults (bare literal, not in the map)"),
    (700, "OTA arming — brick class"),
    (7000, "hidden global pack selector"),
    (11500, "IoT/WiFi provisioning — comms lockout"),
    (30901, "factory test mode"),
    (40001, "grid protection auto-test (bare literal)"),
]


@pytest.mark.parametrize("register,reason", FORBIDDEN)
def test_dangerous_registers_are_refused(register, reason):
    with pytest.raises(ValueError):
        build_switch_payload(register, 1, slave_addr=0, payload_ver=1.2)


def test_permitted_control_registers_still_work():
    for reg in (2011, 2012, 3007, 3008):
        assert build_switch_payload(reg, 1, slave_addr=0, payload_ver=1.2)
