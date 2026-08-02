"""Pack-select must not be blocked by the output-control write guard.

The V1 (AC300) pack-cycling path writes PACK_SELECT (3006) with a pack number
(1..N). That is not an output-control write, so routing it through the switch
guard raised ValueError and broke pack cycling on the README's primary tested
configuration.
"""

import pytest

from custom_components.bluetti_cloud.api.modbus import (
    PACK_SELECT,
    build_pack_select_payload,
)


def test_pack_select_payload_builds_for_valid_pack_numbers():
    for pack in (1, 2, 3, 4):
        payload = build_pack_select_payload(pack, slave_addr=1, payload_ver=1.0)
        assert payload[0] == 0x01          # legacy framing
        assert payload[2] == 0x06          # FC=06
        assert (payload[3] << 8 | payload[4]) == PACK_SELECT


def test_pack_select_rejects_implausible_pack_numbers():
    for pack in (0, 9, -1):
        with pytest.raises(ValueError):
            build_pack_select_payload(pack, slave_addr=1, payload_ver=1.0)
