"""Tests for the declarative device-profile layer."""

from custom_components.bluetti_cloud.api.profiles import (
    AC300_PROFILE,
    AP300_PROFILE,
    DeviceProfile,
    ReadBlock,
    get_profile,
)


def test_ap300_is_rest_only():
    # APEX 300 (model code AP300, protocolVer 2015): fully served by REST,
    # does not speak the current MQTT protocol.
    p = get_profile("AP300", 2015)
    assert p is AP300_PROFILE
    assert p.model == "AP300"
    assert p.data_path == "rest_only"
    assert p.pushes_telemetry is False
    assert p.read_blocks == ()
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


def test_unknown_model_falls_back_to_ac300():
    # Preserves current behavior: unknown devices are treated like the AC300.
    p = get_profile("SOMETHING_NEW", 9999)
    assert p is AC300_PROFILE


def test_profile_is_frozen():
    p = get_profile("AC300", 1018)
    assert isinstance(p, DeviceProfile)
    try:
        p.model = "X"  # type: ignore[misc]
    except Exception as err:
        assert err.__class__.__name__ in ("FrozenInstanceError", "AttributeError")
    else:  # pragma: no cover
        raise AssertionError("DeviceProfile should be immutable")
