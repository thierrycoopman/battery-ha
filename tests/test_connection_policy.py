"""Reconnect policy.

Measured against the real broker: it allows roughly one session per account and
refuses a second with a CONNACK "normal disconnection". That is contention, not
a network fault, and it needs a longer wait than a transport error — retrying
promptly just displaces whichever client currently holds the session.
"""


from custom_components.bluetti_cloud.mqtt.connection import (
    RECONNECT_INITIAL,
    RECONNECT_MAX,
    FailureKind,
    ReconnectPolicy,
    classify_failure,
)


def test_session_conflict_is_recognised():
    assert classify_failure("Connection rejected: Normal disconnection") is (
        FailureKind.SESSION_CONFLICT
    )
    assert classify_failure("no CONNACK received") is FailureKind.SESSION_CONFLICT


def test_transport_errors_are_distinguished():
    assert classify_failure("Cannot reach MQTT broker x:1: timed out") is (
        FailureKind.UNREACHABLE
    )


def test_auth_errors_are_distinguished():
    assert classify_failure("Cannot get server time for MQTT TOTP") is (
        FailureKind.AUTH
    )


def test_first_wait_is_long_enough_for_the_broker():
    """30s was measured as too aggressive; the broker needs longer."""
    policy = ReconnectPolicy()
    assert policy.next_delay(FailureKind.UNREACHABLE) >= RECONNECT_INITIAL


def test_a_contended_session_waits_longer_than_a_network_error():
    a, b = ReconnectPolicy(), ReconnectPolicy()
    assert (a.next_delay(FailureKind.SESSION_CONFLICT)
            > b.next_delay(FailureKind.UNREACHABLE))


def test_backoff_grows_and_is_capped():
    policy = ReconnectPolicy()
    delays = [policy.next_delay(FailureKind.UNREACHABLE) for _ in range(10)]
    assert delays[0] < delays[3]
    assert all(d <= RECONNECT_MAX for d in delays)


def test_delays_are_jittered_so_clients_do_not_collide():
    a = [ReconnectPolicy().next_delay(FailureKind.UNREACHABLE) for _ in range(12)]
    assert len(set(a)) > 1, "identical delays make restarts collide repeatedly"


def test_success_resets_the_backoff():
    policy = ReconnectPolicy()
    for _ in range(5):
        policy.next_delay(FailureKind.UNREACHABLE)
    grown = policy.next_delay(FailureKind.UNREACHABLE)
    policy.reset()
    assert policy.next_delay(FailureKind.UNREACHABLE) < grown
