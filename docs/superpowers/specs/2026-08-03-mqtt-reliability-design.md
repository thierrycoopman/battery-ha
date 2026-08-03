# MQTT reliability redesign

**Status:** approved in session, 2026-08-03

## Problem

Reported symptoms: entities go unavailable or stale, and MQTT will not connect
or keeps dropping.

Structural causes found:

- `_pending_request` is a single global slot. One request in flight at a time,
  and every unsolicited push races with it. Most of the worst bugs this project
  has hit trace here: a cell block decoded as a pack record (SOC 252%, 3284 C),
  unsolicited homeData decoded with the wrong layout (SOC 12336), replies
  overtaking their requests.
- `mqtt_manager.py` is 1256 lines covering connection lifecycle, reconnection,
  polling, correlation, frame routing, block parsing and node bookkeeping.
- Reconnect backoff starts at 30s; measured broker behaviour needs ~45s. No
  jitter. Certificates and TOTP are re-fetched on every attempt.
- The broker appears to allow one session per account, so a competing client
  (the mobile app, or a test script) silently displaces Home Assistant.

## Design

Five modules, dependencies strictly downward:

| Module | Responsibility | Knows nothing about |
|---|---|---|
| `mqtt/connection.py` | paho client, TLS, certs, connect/reconnect policy | registers, blocks |
| `mqtt/transport.py` | request → reply correlation, several in flight | register meanings |
| `mqtt/decoder.py` | frame bytes → typed block; pure | MQTT, sockets |
| `mqtt/poller.py` | what to read and when; push-aware | transport internals |
| `mqtt_manager.py` | orchestration, overlays, coordinator glue | — |

### Transport

Each request registers a pending entry keyed by what the reply will look like —
`(register, slave_addr, expected_length)` — and receives its own `Future`.
Incoming frames are matched against outstanding entries; anything unmatched is
treated as unsolicited telemetry rather than as an answer to the last question
asked. This removes the misattribution class of bug by construction instead of
by guard, and lets concurrent requests proceed without interfering.

### Connection

- Treat a CONNACK refusal of "normal disconnection" as a contended session, not
  a network fault: back off longer and say so in the log.
- Backoff starts at 45s with jitter.
- Cache certificates across reconnects rather than re-deriving per attempt.
- Availability is decoupled from any single poll result.

### Testing

A replay harness feeds captured frames through the real stack, so every bug
found so far becomes an offline regression test. This also removes the need to
hold the broker session to verify, which was itself displacing the user's Home
Assistant.

## Non-goals

Entity IDs, device structure, the profile layer and the REST path are unchanged.
This is the transport beneath them.
