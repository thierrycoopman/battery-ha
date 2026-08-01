"""Tests for the declarative device-profile layer."""

from custom_components.bluetti_cloud.api.profiles import (
    AC300_PROFILE,
    AP300_PROFILE,
    DeviceProfile,
    ReadBlock,
    get_profile,
)


def test_ap300_is_mqtt_rest_poll_driven():
    # APEX 300 (model code AP300, protocolVer 2015): MQTT+REST, poll-driven,
    # 2nd-gen IoT (slave 0, iotPayloadVer 1.2). Telemetry only for now —
    # control (switch registers) is added in a later step.
    p = get_profile("AP300", 2015)
    assert p is AP300_PROFILE
    assert p.model == "AP300"
    assert p.data_path == "mqtt+rest"
    assert p.pushes_telemetry is False
    assert p.slave_addr == 0
    assert p.iot_payload_ver == 1.2
    assert {b.name for b in p.read_blocks} == {
        "home_data", "pack_main_info", "pack_item_info"
    }
    # Not controllable yet (telemetry-first).
    assert p.controllable is False
    assert p.ac_switch_reg is None
    assert p.dc_switch_reg is None


def test_ap300_matches_any_protocol_ver():
    # Match on model regardless of the exact reported protocol version.
    assert get_profile("AP300", 2015) is AP300_PROFILE
    assert get_profile("AP300", 0) is AP300_PROFILE


def test_ac300_stays_mqtt_rest_after_ap300_added():
    assert get_profile("AC300", 1018).data_path == "mqtt+rest"


def test_ac300_profile_shape():
    p = get_profile("AC300", 1018)
    assert p.model == "AC300"
    assert p.data_path == "mqtt+rest"
    assert p.pushes_telemetry is True
    assert p.slave_addr == 1
    assert p.ac_switch_reg == 3007
    assert p.dc_switch_reg == 3008
    assert p.pack_select_reg == 3006
    assert p.switch_encoding == "simple"


def test_ac300_read_blocks():
    p = get_profile("AC300", 1018)
    by_name = {b.name: b for b in p.read_blocks}
    assert by_name["home_data"] == ReadBlock("home_data", 100, 62, "home_data")
    assert by_name["pack_main_info"].register == 6000
    assert by_name["pack_main_info"].count == 34
    assert by_name["pack_item_info"].register == 6100
    assert by_name["pack_item_info"].count == 90


def test_unknown_model_falls_back_by_protocol_generation():
    # Unknown V1-era devices keep the original AC300 behavior...
    assert get_profile("SOMETHING_OLD", 1500) is AC300_PROFILE
    # ...but an unknown 2nd-gen device must get V2 framing, not V1.
    assert get_profile("SOMETHING_NEW", 9999).iot_payload_ver == 1.2


def test_profile_is_frozen():
    p = get_profile("AC300", 1018)
    assert isinstance(p, DeviceProfile)
    try:
        p.model = "X"  # type: ignore[misc]
    except Exception as err:
        assert err.__class__.__name__ in ("FrozenInstanceError", "AttributeError")
    else:  # pragma: no cover
        raise AssertionError("DeviceProfile should be immutable")


def test_unknown_v2_device_gets_v2_profile_not_v1():
    """An unknown model reporting protocolVer >= 2000 must not get the V1 profile.

    V2 devices need the 01F80F payload envelope and Modbus slave 0; handing them
    the legacy V1 profile would produce frames the device ignores.
    """
    p = get_profile("SOME_NEW_V2_MODEL", 2015)
    assert p.data_path == "mqtt+rest"
    assert p.iot_payload_ver == 1.2
    assert p.slave_addr == 0
    assert p.pushes_telemetry is False
    # Unknown model: don't claim controllability we haven't verified.
    assert p.controllable is False


def test_unknown_v1_device_still_falls_back_to_ac300():
    p = get_profile("SOME_OLD_MODEL", 1018)
    assert p is AC300_PROFILE
