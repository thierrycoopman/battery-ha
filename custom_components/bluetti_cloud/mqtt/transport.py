"""Request/reply correlation for the Bluetti MQTT protocol.

The device's replies carry no request identifier, so a reply has to be matched
against the requests actually outstanding. The signal available is what the
reply looks like: the slave address in the frame, and its payload length.

The previous design tracked a single "pending request" and treated whatever
arrived next as its answer. That is wrong whenever the device also pushes
telemetry unprompted — which this hardware does constantly — and it produced
cell blocks decoded as pack records and unsolicited data decoded with the wrong
layout. Here, a frame that matches no outstanding request is unsolicited
telemetry by definition, never an answer.

Requests may be in flight concurrently; each waits on its own future.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 8.0


@dataclass(frozen=True)
class Reply:
    """A decoded Modbus reply: who sent it, and what it contains."""

    slave: int
    length: int
    data: bytes


@dataclass(frozen=True)
class _Pending:
    """What an outstanding request expects its reply to look like."""

    slave: int
    length: int

    def matches(self, reply: Reply) -> bool:
        # Slave 0 is the main unit's own address, so compare by value.
        return reply.slave == self.slave and reply.length == self.length


# (register, slave, count, payload_ver) -> None
SendFn = Callable[[int, int, int, float], None]
UnsolicitedFn = Callable[[Reply], None]


class Transport:
    """Issues requests and resolves them against incoming frames."""

    def __init__(
        self,
        send: SendFn,
        on_unsolicited: UnsolicitedFn | None = None,
    ) -> None:
        self._send = send
        self.on_unsolicited: UnsolicitedFn | None = on_unsolicited
        self._waiters: list[tuple[_Pending, asyncio.Future[Reply]]] = []

    @property
    def outstanding(self) -> int:
        """How many requests are awaiting a reply."""
        return len(self._waiters)

    async def request(
        self,
        register: int,
        slave: int,
        count: int,
        payload_ver: float = 1.0,
        # ASYNC109: the timeout belongs to this layer rather than the caller —
        # it bounds how long the *device* may take to answer, and the pending
        # entry has to be released here whatever the outcome.
        timeout: float = DEFAULT_TIMEOUT,  # noqa: ASYNC109
    ) -> Reply:
        """Send a read and wait for the reply that matches it.

        Raises:
            asyncio.TimeoutError: if no matching reply arrives in time.
            ConnectionError: if the connection drops while waiting.
        """
        expected = _Pending(slave=slave, length=count * 2)
        future: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
        entry = (expected, future)
        self._waiters.append(entry)

        try:
            self._send(register, slave, count, payload_ver)
            return await asyncio.wait_for(future, timeout)
        finally:
            # Always release the slot, whether answered, timed out or cancelled.
            if entry in self._waiters:
                self._waiters.remove(entry)

    def on_frame(self, reply: Reply) -> None:
        """Route an incoming frame to the request it answers, if any."""
        for entry in list(self._waiters):
            expected, future = entry
            if not expected.matches(reply) or future.done():
                continue
            self._waiters.remove(entry)
            future.set_result(reply)
            return

        # Nothing was waiting for this shape of frame, so the device sent it on
        # its own. Treating it as an answer is what corrupted readings before.
        if self.on_unsolicited is not None:
            self.on_unsolicited(reply)

    def abort(self, reason: str) -> None:
        """Fail every outstanding request — the connection went away."""
        if self._waiters:
            _LOGGER.debug("Aborting %d in-flight request(s): %s",
                          len(self._waiters), reason)
        for _expected, future in list(self._waiters):
            if not future.done():
                future.set_exception(ConnectionError(reason))
        self._waiters.clear()
