"""Tests for Bluetti's general payload-encoding conventions (V2).

Derived from the app's shared helpers:
  - ASCII fields are byte-swapped within each 16-bit register (lo then hi)
  - serial numbers reverse register order then render as a decimal u64
  - 32-bit values are register(word)-swapped
"""

from custom_components.bluetti_cloud.api.modbus import (
    ascii_swapped,
    device_sn_from_registers,
    u32_word_swapped,
)


def test_ascii_swapped_decodes_model_names():
    # Raw "PA03\0 0" decodes to "AP300" under per-register byte swap.
    assert ascii_swapped(bytes.fromhex("504130330030000000000000")) == "AP300"
    # The external pack's raw '3B00' is really "B300".
    assert ascii_swapped(bytes.fromhex("33423030")) == "B300"


def test_ascii_swapped_skips_padding():
    assert ascii_swapped(bytes.fromhex("0000000000000000")) == ""


def test_device_sn_reverses_register_order():
    # Real AP300 SN bytes -> the device's numeric SN tail.
    sn_bytes = bytes.fromhex("de4c1c8302610000")
    assert device_sn_from_registers(sn_bytes) == "2616113487436"


def test_u32_word_swapped():
    # low register first, then high: A32C 0001 -> 0x0001A32C
    assert u32_word_swapped(bytes.fromhex("a32c0001")) == 0x0001A32C
