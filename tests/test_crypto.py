"""Tests for Bluetti password transformation (crypto module)."""

from custom_components.bluetti_cloud.api.crypto import (
    derive_aes_key,
    encrypt_password,
    hash_password,
)

# Synthetic test vector (computed locally, not from real credentials)
TEST_PASSWORD = "TestPassword123!"
EXPECTED_SHA256 = "FFC121A2210958BF74E5A874668F3D978D24B6A8241496CCFF3C0EA245E4F126"
EXPECTED_AES_KEY = "FF376DB6166553D2B18A8B4CB0BA9957"
EXPECTED_PASS_OPEN = "b890d65b4cad5e88b713c465bda69ec02cff13ed3ea675b79b7944e70d5281cd"


def test_hash_password():
    assert hash_password(TEST_PASSWORD) == EXPECTED_SHA256


def test_hash_password_is_uppercase():
    result = hash_password("test")
    assert result == result.upper()


def test_derive_aes_key():
    assert derive_aes_key(TEST_PASSWORD) == EXPECTED_AES_KEY


def test_derive_aes_key_is_uppercase():
    result = derive_aes_key("test")
    assert result == result.upper()


def test_encrypt_password():
    assert encrypt_password(TEST_PASSWORD) == EXPECTED_PASS_OPEN


def test_encrypt_password_is_lowercase_hex():
    result = encrypt_password(TEST_PASSWORD)
    assert result == result.lower()
    assert all(c in "0123456789abcdef" for c in result)


def test_short_password():
    """Ensure short passwords (< 16 bytes) are padded correctly."""
    result = encrypt_password("abc")
    assert len(result) == 32  # 16 bytes padded → 16 bytes encrypted → 32 hex chars


def test_exact_block_password():
    """16-char password should produce 2 blocks (PKCS7 adds full padding block)."""
    result = encrypt_password("a" * 16)
    assert len(result) == 64  # 32 bytes encrypted → 64 hex chars
