"""Connection policy for the Bluetti MQTT broker.

The broker behaves in ways worth encoding rather than rediscovering:

* It appears to allow roughly **one session per account**. A second client is
  refused with a CONNACK of "normal disconnection" — the TLS handshake
  succeeds, then the session is closed. An open Bluetti mobile app will do this
  to Home Assistant, and so will any other client using the same credentials.
* It rate-limits reconnection. Retrying after 30s was measured as too soon;
  around 45s succeeds.

Both look identical to a naive "connection failed" handler, but they call for
different responses: a contended session needs patience (another client holds
it), while an unreachable broker is worth retrying sooner. Classifying the
failure lets the log say which it is, instead of leaving the user guessing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

# Measured: 30s is too aggressive for this broker, ~45s succeeds.
RECONNECT_INITIAL = 45.0
RECONNECT_MAX = 600.0
# A contended session will not clear by asking sooner; wait longer than for a
# transport error, and avoid displacing whichever client currently holds it.
SESSION_CONFLICT_MULTIPLIER = 2.0
# Spread retries so several clients (or a restart storm) don't collide. Jitter
# only ever extends a wait: 45s is the measured-safe floor, so retrying sooner
# than that just fails again.
JITTER = 0.25


class FailureKind(Enum):
    """Why a connection attempt failed, to the extent it can be told."""

    SESSION_CONFLICT = "session_conflict"
    UNREACHABLE = "unreachable"
    AUTH = "auth"
    UNKNOWN = "unknown"

    @property
    def explanation(self) -> str:
        """A description a user can act on."""
        return {
            FailureKind.SESSION_CONFLICT: (
                "another client holds the account's MQTT session — close the "
                "Bluetti mobile app if it is open"
            ),
            FailureKind.UNREACHABLE: (
                "the broker could not be reached — check network access to "
                "port 18760"
            ),
            FailureKind.AUTH: (
                "authentication or certificate exchange failed"
            ),
            FailureKind.UNKNOWN: "reason unclear",
        }[self]


def classify_failure(message: str) -> FailureKind:
    """Work out what a connection failure means from its message."""
    text = (message or "").lower()
    # The TLS layer connected but the session was refused or never confirmed:
    # that is the signature of the account's single session being held.
    if "normal disconnection" in text or "connack" in text or "rejected" in text:
        return FailureKind.SESSION_CONFLICT
    if "cannot reach" in text or "timed out" in text or "unreachable" in text:
        return FailureKind.UNREACHABLE
    if any(k in text for k in ("token", "server time", "certificate", "pfx",
                              "user id", "authenticated")):
        return FailureKind.AUTH
    return FailureKind.UNKNOWN


@dataclass
class ReconnectPolicy:
    """Decides how long to wait before the next attempt."""

    _attempt: int = field(default=0, repr=False)

    def next_delay(self, kind: FailureKind) -> float:
        """Delay before the next attempt, growing with consecutive failures."""
        base = min(RECONNECT_INITIAL * (2 ** self._attempt), RECONNECT_MAX)
        self._attempt += 1
        if kind is FailureKind.SESSION_CONFLICT:
            base = min(base * SESSION_CONFLICT_MULTIPLIER, RECONNECT_MAX)
        # Extend, never shorten — and stay within the cap.
        return round(min(base * (1.0 + random.uniform(0, JITTER)),
                         RECONNECT_MAX), 2)

    def reset(self) -> None:
        """A connection succeeded — start again from the shortest delay."""
        self._attempt = 0
