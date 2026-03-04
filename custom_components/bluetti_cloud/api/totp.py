"""TOTP authentication for Bluetti MQTT broker.

Ported from the Bluetti mobile app (APK v3.0.6) TotpUtils.java.
The MQTT password is a time-based one-time password derived from
the API token and a shared private key.
"""

import hashlib
import time

SHARED_PRIVATE_KEY = "ga3sa4hj6kfl"
T0 = 1371517200  # Epoch reference (~2013-06-18)
STEP = 30  # seconds
CODE_DIGITS = 8
DIGITS_POWER = [1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000]


def _md5_encode(data: bytes) -> str:
    """MD5 hash as lowercase hex string."""
    return hashlib.md5(data).hexdigest()


def _build_kvalue(token_part1: str, token_part0: str) -> str:
    """Build the TOTP key from token parts.

    Args:
        token_part1: Second part of JWE token (split by '.').
        token_part0: First part of JWE token.

    Returns:
        Derived key string.
    """
    first2 = token_part1[:2]
    last2 = token_part1[-2:]
    shared_first6 = SHARED_PRIVATE_KEY[:6]  # "ga3sa4"
    shared_remainder = SHARED_PRIVATE_KEY.replace(shared_first6, "", 1)  # "hj6kfl"
    return first2 + shared_first6 + token_part0 + shared_remainder + last2


def _encrypt(time_bytes: bytes, key_bytes: bytes) -> bytes:
    """Interleave MD5 hashes of time factor and key.

    Returns 64-byte result from interleaving two 32-char hex strings.
    """
    md5_time = _md5_encode(time_bytes).upper()
    md5_key = _md5_encode(key_bytes).upper()
    result = []
    for i in range(len(md5_time)):
        result.append(md5_key[i])
        result.append(md5_time[i])
    return "".join(result).encode("utf-8")


def _truncate(data: bytes) -> str:
    """RFC 4226 dynamic truncation to 8-digit numeric string."""
    offset = data[-1] & 0x0F
    code = (
        ((data[offset] & 0x7F) << 24)
        | ((data[offset + 1] & 0xFF) << 16)
        | ((data[offset + 2] & 0xFF) << 8)
        | (data[offset + 3] & 0xFF)
    )
    otp = code % DIGITS_POWER[CODE_DIGITS]
    return str(otp).zfill(CODE_DIGITS)


def _hex_string_to_bytes(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str)


def generate_totp(token_part1: str, token_part0: str, utc_millis: int | None = None) -> str:
    """Generate TOTP password for MQTT authentication.

    Args:
        token_part1: Second part of JWE token (token.split('.')[1]).
        token_part0: First part of JWE token (token.split('.')[0]).
        utc_millis: UTC time in milliseconds. Defaults to current time.

    Returns:
        8-digit TOTP password string.
    """
    if utc_millis is None:
        utc_millis = int(time.time() * 1000)

    time_factor = ((utc_millis // 1000) - T0) // STEP

    # Hex-encode time factor to 16-char uppercase hex string
    hex_time = format(time_factor, "016X")
    time_bytes = _hex_string_to_bytes(hex_time)

    kvalue = _build_kvalue(token_part1, token_part0)
    key_bytes = kvalue.encode("utf-8")

    encrypted = _encrypt(time_bytes, key_bytes)
    return _truncate(encrypted)


def derive_mqtt_credentials(token: str) -> tuple[str, str, str]:
    """Derive MQTT username and password from API token.

    Args:
        token: JWE token from API login (dot-separated parts).

    Returns:
        Tuple of (client_id, username, password).
    """
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid token format: expected dot-separated JWE token")

    username = f"tid:{parts[1]}"
    password = generate_totp(parts[1], parts[0])

    # Client ID: MD5 of a unique string
    unique = f"BLUETTI_HA&{int(time.time() * 1000)}"
    client_id = hashlib.md5(unique.encode("utf-8")).hexdigest()

    return client_id, username, password
