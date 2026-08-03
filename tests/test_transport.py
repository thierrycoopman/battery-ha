"""Request/reply correlation.

Replies are matched against the requests actually outstanding, keyed by what
the reply will look like. Anything unmatched is unsolicited telemetry, never an
answer to whatever was asked last — that assumption produced a cell block
decoded as a pack record, and unsolicited data decoded with the wrong layout.
"""

import asyncio

import pytest

from custom_components.bluetti_cloud.api.modbus import NODE_INFO
from custom_components.bluetti_cloud.mqtt.transport import Reply, Transport


@pytest.fixture
def transport():
    sent: list = []
    t = Transport(send=lambda register, slave, count, payload_ver: sent.append(
        (register, slave, count)))
    t.sent = sent
    return t


@pytest.mark.asyncio
async def test_reply_resolves_the_matching_request(transport):
    task = asyncio.create_task(transport.request(6100, slave=51, count=104))
    await asyncio.sleep(0)
    transport.on_frame(Reply(slave=51, length=208, data=bytes(208)))
    assert (await task).data == bytes(208)


@pytest.mark.asyncio
async def test_two_requests_in_flight_do_not_interfere(transport):
    a = asyncio.create_task(transport.request(6100, slave=0, count=104))
    b = asyncio.create_task(transport.request(6100, slave=51, count=104))
    await asyncio.sleep(0)

    # Replies arrive out of order; each must resolve its own request.
    transport.on_frame(Reply(slave=51, length=208, data=b"\x51" * 208))
    transport.on_frame(Reply(slave=0, length=208, data=b"\x00" * 208))

    assert (await a).data[:1] == b"\x00"
    assert (await b).data[:1] == b"\x51"


@pytest.mark.asyncio
async def test_a_frame_matching_nothing_is_unsolicited(transport):
    seen: list = []
    transport.on_unsolicited = seen.append
    transport.on_frame(Reply(slave=51, length=124, data=bytes(124)))
    assert seen, "unmatched frames must surface as telemetry, not be discarded"


@pytest.mark.asyncio
async def test_a_wrong_sized_reply_does_not_satisfy_a_request(transport):
    """A 50-byte cell block must never resolve a 208-byte pack request."""
    task = asyncio.create_task(transport.request(6100, slave=51, count=104))
    await asyncio.sleep(0)
    transport.on_frame(Reply(slave=51, length=50, data=bytes(50)))
    assert not task.done()
    task.cancel()


@pytest.mark.asyncio
async def test_slave_zero_is_a_real_address(transport):
    """The main unit answers at slave 0; a truthiness check loses it."""
    task = asyncio.create_task(transport.request(6100, slave=0, count=104))
    await asyncio.sleep(0)
    transport.on_frame(Reply(slave=0, length=208, data=bytes(208)))
    assert (await task).slave == 0


@pytest.mark.asyncio
async def test_a_request_that_is_never_answered_times_out(transport):
    with pytest.raises(asyncio.TimeoutError):
        await transport.request(6100, slave=99, count=104, timeout=0.05)
    # and it must not leak a pending entry
    assert transport.outstanding == 0


@pytest.mark.asyncio
async def test_shutdown_fails_waiters_rather_than_hanging(transport):
    task = asyncio.create_task(transport.request(6100, slave=51, count=104))
    await asyncio.sleep(0)
    transport.abort("connection lost")
    with pytest.raises(ConnectionError):
        await task


@pytest.mark.asyncio
async def test_a_reply_smaller_than_requested_still_answers_the_request():
    """The device answers with the registers it has, not the number asked for.

    A 16-cell pack returns 44 bytes to a 50-byte request. Requiring the
    requested size meant no reply ever matched and every poll ran to its
    timeout — which is exactly what shipped in v0.14.0.
    """
    transport = Transport(send=lambda *a: None)
    pending = asyncio.create_task(transport.request(NODE_INFO, 0, 26))
    await asyncio.sleep(0)

    transport.on_frame(Reply(slave=0, length=44, data=bytes(44)))
    reply = await asyncio.wait_for(pending, timeout=1)
    assert reply.length == 44


@pytest.mark.asyncio
async def test_a_frame_recognised_as_another_block_is_not_an_answer():
    """Accepting any size must not mean accepting any frame."""
    transport = Transport(send=lambda *a: None)
    pending = asyncio.create_task(transport.request(6100, 51, 104))
    await asyncio.sleep(0)

    # Streaming telemetry from the same pack, recognisably a different block.
    transport.on_frame(Reply(slave=51, length=44, data=bytes(44), block=6300))
    await asyncio.sleep(0)
    assert not pending.done()

    transport.on_frame(Reply(slave=51, length=180, data=bytes(180)))
    await asyncio.wait_for(pending, timeout=1)


@pytest.mark.asyncio
async def test_a_refusal_fails_only_the_request_it_answers():
    """A refusal names no register, so it belongs to that address's oldest read."""
    transport = Transport(send=lambda *a: None)
    refused = asyncio.create_task(transport.request(6100, 51, 104))
    other = asyncio.create_task(transport.request(6300, 0, 25))
    await asyncio.sleep(0)

    transport.fail(51, RuntimeError("illegal data address"))

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(refused, timeout=1)
    assert not other.done(), "an unrelated address must keep waiting"
    other.cancel()
