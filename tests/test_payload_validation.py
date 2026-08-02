"""A payload must fit the layout before it is decoded.

Replies can arrive out of order with respect to the request that is pending, so
dispatching on the pending register alone is not enough. A 50-byte cell block
decoded with the 208-byte pack-item layout produced SOC 252, 33.24 V and
3284 C — plausible-looking numbers that are entirely wrong.
"""

from unittest.mock import MagicMock

from custom_components.bluetti_cloud.api.profiles import AP300_PROFILE
from custom_components.bluetti_cloud.mqtt_manager import BluettiMqttManager

PARENT = "AP3002616113487436"


def _manager():
    coordinator = MagicMock()
    coordinator.data = {PARENT: {"device_type": "AP300", "sub_sn": "X"}}
    coordinator.profile_for.return_value = AP300_PROFILE
    mgr = BluettiMqttManager(coordinator)
    mgr.overlays[PARENT] = {"nodes": [
        {"slave_addr": 51, "model": 4005, "model_name": "B300",
         "is_battery": True, "online": True},
    ]}
    return mgr


def _real_cell_block() -> bytes:
    """A cell block as the device actually sends it: 16 cells near 3.32 V."""
    data = bytearray(50)
    data[1] = 16   # cell count
    data[3] = 4    # ntc count
    for i in range(16):
        mv = 3320 + (i % 4)
        data[4 + 2 * i] = (mv >> 8) & 0xFF
        data[5 + 2 * i] = mv & 0xFF
    return bytes(data)


def test_cell_sized_payload_is_not_decoded_as_a_pack_record():
    """This is the exact failure seen live: SOC 252, 33.24 V, 3284 C."""
    mgr = _manager()
    mgr._route_register_data(PARENT, 6100, 51, _real_cell_block())
    node = mgr.overlays[PARENT]["nodes"][0]
    assert "pack_soc" not in node
    assert "pack_voltage" not in node
    assert "pack_temperature" not in node


def test_pack_sized_payload_is_not_decoded_as_cells():
    mgr = _manager()
    mgr._route_register_data(PARENT, 6300, 51, bytes(208))  # pack-sized
    node = mgr.overlays[PARENT]["nodes"][0]
    assert "cell_voltage_delta" not in node


def test_correctly_sized_payloads_still_decode():
    mgr = _manager()
    pack = bytearray(208)
    pack[27] = 94
    pack[105] = 16
    raw = b"B300" + b"\x00" * 8
    for i in range(6):
        pack[2 + i * 2] = raw[i * 2 + 1]
        pack[3 + i * 2] = raw[i * 2]
    mgr._route_register_data(PARENT, 6100, 51, bytes(pack))
    node = mgr.overlays[PARENT]["nodes"][0]
    assert node["pack_soc"] == 94
    assert node["pack_model"] == "B300"
