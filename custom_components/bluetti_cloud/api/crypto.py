"""Password transformation for Bluetti mobile app authentication.

The Bluetti mobile app (APK v3.0.6) requires a specific password transformation:
1. 'password' field = SHA-256 hash of plaintext, uppercase hex
2. AES key = MD5 of the SHA-256 hash, uppercase hex
3. 'passOpen' field = AES-256-ECB encrypt plaintext with that key, hex encoded
"""

import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def hash_password(plaintext: str) -> str:
    """SHA-256 hash of password, uppercase hex. Used as 'password' field."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest().upper()


def derive_aes_key(plaintext: str) -> str:
    """Derive AES key: MD5(SHA256(pw).upper()).upper()."""
    sha = hash_password(plaintext)
    return hashlib.md5(sha.encode("utf-8")).hexdigest().upper()


def encrypt_password(plaintext: str) -> str:
    """AES-256-ECB encrypt password, hex encoded. Used as 'passOpen' field."""
    key = derive_aes_key(plaintext)
    cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(plaintext.encode("utf-8"), 16))
    return encrypted.hex()
