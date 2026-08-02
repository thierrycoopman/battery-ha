"""Fixes from an independent audit of the implementation against the app."""

from custom_components.bluetti_cloud.api.modbus import (
    parse_home_data,
    parse_inv_grid_info,
    parse_node_info,
)


def _home(**at) -> bytes:
    data = bytearray(124)
    for off, raw in at.items():
        i = int(off.lstrip("b"))
        data[i:i + len(raw)] = raw
    return bytes(data)


def test_home_data_32bit_fields_are_word_swapped():
    """32-bit values store the low register first, like every other such field."""
    # 0x0001A32C written low-register-first is A32C 0001
    data = _home(b80=bytes.fromhex("a32c0001"))
    assert parse_home_data(data)["total_dc_power"] == 0x0001A32C


def test_home_data_energy_totals_are_word_swapped():
    data = _home(b100=bytes.fromhex("00640000"))  # -> 0x00000064 = 100 -> 10.0 kWh
    assert parse_home_data(data)["total_dc_energy"] == 10.0


def test_home_data_model_and_serial_use_the_swapped_encoding():
    """These fields follow the same conventions as everywhere else."""
    model = bytearray(12)
    raw = b"AP300" + b"\x00" * 7
    for i in range(6):
        model[i * 2] = raw[i * 2 + 1]
        model[i * 2 + 1] = raw[i * 2]
    data = _home(b20=bytes(model), b32=bytes.fromhex("de4c1c8302610000"))
    parsed = parse_home_data(data)
    assert parsed["device_model"] == "AP300"
    assert parsed["device_sn"] == "2616113487436"


def test_grid_power_handles_export_without_overflowing():
    """The app takes the signed value's magnitude; an unsigned read turns a
    small export into billions of watts."""
    data = bytearray(40)
    data[25] = 1                       # one phase
    data[2:6] = bytes.fromhex("ff9c ffff".replace(" ", ""))  # -100 word-swapped
    parsed = parse_inv_grid_info(bytes(data))
    assert parsed["grid_power"] == 100


def test_node_serial_is_rendered_like_every_other_serial():
    """A node record is 4 header bytes + 16 per node; the serial sits at 6:14."""
    header = bytes.fromhex("00010001")
    node = bytearray(16)
    node[1] = 51                                        # slave address
    node[6:14] = bytes.fromhex("de4c1c8302610000")      # serial
    node[14:16] = (4005).to_bytes(2, "big")             # B300
    nodes = parse_node_info(header + bytes(node))
    assert nodes[0]["sn"] == "2616113487436"
