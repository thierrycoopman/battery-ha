"""Sub-devices should be real HA devices, linked to their parent unit.

A flat entity list does not scale: this setup already has a B300 battery and a
D1 hub, and a B300K and A1 hub are expected later. Each expansion becomes its
own device so a dashboard can target it directly, and so two batteries of
different models never collide.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.entity import BluettiSubDeviceEntity

PARENT = "AP3002616113487436"

B300 = {
    "slave_addr": 51, "model": 4005, "model_name": "B300",
    "is_battery": True, "online": True, "sn": "de4c",
}
B300K = {
    "slave_addr": 52, "model": 4006, "model_name": "B300K",
    "is_battery": True, "online": True, "sn": "aa11",
}
D1_HUB = {
    "slave_addr": 11, "model": 3007, "model_name": "D1 Hub (HD1)",
    "is_battery": False, "online": True, "sn": "e06c",
}


def _coordinator(nodes):
    coordinator = MagicMock()
    coordinator.data = {PARENT: {"device_name": "APEX", "device_type": "AP300",
                                 "nodes": nodes}}
    coordinator._device_info = {}
    coordinator.get_nodes.return_value = nodes
    return coordinator


def test_sub_device_is_its_own_device_linked_to_the_parent():
    coordinator = _coordinator([B300])
    ent = BluettiSubDeviceEntity(coordinator, PARENT, 51, "battery")
    info = ent.device_info
    # Its own identity, not the parent's
    assert (("bluetti_cloud", f"{PARENT}_node_51")) in info["identifiers"]
    # Linked to the parent unit so HA nests it
    assert info["via_device"] == ("bluetti_cloud", PARENT)
    assert info["name"] == "B300"
    assert info["model"] == "B300"


def test_two_batteries_of_different_models_do_not_collide():
    coordinator = _coordinator([B300, B300K])
    a = BluettiSubDeviceEntity(coordinator, PARENT, 51, "battery")
    b = BluettiSubDeviceEntity(coordinator, PARENT, 52, "battery")
    assert a.unique_id != b.unique_id
    assert a.device_info["identifiers"] != b.device_info["identifiers"]
    assert a.device_info["name"] == "B300"
    assert b.device_info["name"] == "B300K"


def test_hub_is_modelled_the_same_way():
    coordinator = _coordinator([D1_HUB])
    ent = BluettiSubDeviceEntity(coordinator, PARENT, 11, "status")
    assert ent.device_info["name"] == "D1 Hub (HD1)"
    assert ent.node["is_battery"] is False


def test_unknown_expansion_still_gets_a_device():
    """A model we haven't catalogued must still appear, not vanish."""
    unknown = {"slave_addr": 60, "model": 4099, "model_name": "Battery (4099)",
               "is_battery": True, "online": True, "sn": "ffff"}
    coordinator = _coordinator([unknown])
    ent = BluettiSubDeviceEntity(coordinator, PARENT, 60, "battery")
    assert ent.device_info["name"] == "Battery (4099)"


def test_node_lookup_survives_a_missing_node():
    coordinator = _coordinator([])
    ent = BluettiSubDeviceEntity(coordinator, PARENT, 51, "battery")
    assert ent.node == {}
    assert ent.available is False


def test_main_unit_internal_battery_is_named_clearly():
    """Calling it "AP300" again would be confusing next to the parent device."""
    internal = {"slave_addr": 0, "model": 6, "model_name": "AP300",
                "is_battery": False, "has_battery": True, "online": True}
    coordinator = _coordinator([internal])
    ent = BluettiSubDeviceEntity(coordinator, PARENT, 0, "soc")
    assert ent.device_info["name"] == "Internal Battery"


def test_internal_battery_gets_battery_entities():
    from custom_components.bluetti_cloud.subdevice import build_sub_device_entities

    internal = {"slave_addr": 0, "model": 6, "model_name": "AP300",
                "is_battery": False, "has_battery": True, "online": True}
    coordinator = _coordinator([internal])
    ents = build_sub_device_entities(coordinator, PARENT, internal)
    keys = {e.unique_id.rsplit("_", 1)[-1] for e in ents}
    assert "soc" in keys


def test_hub_does_not_get_battery_entities():
    from custom_components.bluetti_cloud.subdevice import build_sub_device_entities

    coordinator = _coordinator([D1_HUB])
    ents = build_sub_device_entities(coordinator, PARENT, D1_HUB)
    keys = {e.unique_id.rsplit("_", 1)[-1] for e in ents}
    assert "soc" not in keys
    assert "online" in keys and "fault" in keys
