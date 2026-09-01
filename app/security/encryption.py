"""AES-256-GCM token encryption.

A fresh random 12-byte IV (nonce) is generated for every encryption, so
encrypting the same token twice yields different ciphertext. Ciphertext and IV
are stored separately; the plaintext is never persisted or logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

IV_SIZE = 12  # 96-bit nonce, the recommended size for GCM


class DecryptionError(Exception):
    """Raised when ciphertext fails authentication (tampered or wrong key)."""


@dataclass(frozen=True)
class EncryptedBlob:
    ciphertext: bytes
    iv: bytes


def encrypt_token(plaintext: str, key: bytes | None = None) -> EncryptedBlob:
    key = key or get_settings().encryption_key
    iv = os.urandom(IV_SIZE)
    ciphertext = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return EncryptedBlob(ciphertext=ciphertext, iv=iv)


def decrypt_token(ciphertext: bytes, iv: bytes, key: bytes | None = None) -> str:
    key = key or get_settings().encryption_key
    try:
        return AESGCM(key).decrypt(iv, ciphertext, None).decode("utf-8")
    except InvalidTag as exc:  # pragma: no cover - exercised in tests
        raise DecryptionError("token failed authentication") from exc
