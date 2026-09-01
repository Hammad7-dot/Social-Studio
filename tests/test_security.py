"""Token encryption at rest and no-plaintext-leak guarantees."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.models.token import PlatformToken
from app.security.encryption import DecryptionError, decrypt_token, encrypt_token

SECRET_TOKEN = "SUPER-SECRET-PLATFORM-TOKEN-abcdef123456"


def test_encrypt_decrypt_roundtrip():
    blob = encrypt_token(SECRET_TOKEN)
    assert decrypt_token(blob.ciphertext, blob.iv) == SECRET_TOKEN


def test_fresh_iv_per_encryption():
    a = encrypt_token(SECRET_TOKEN)
    b = encrypt_token(SECRET_TOKEN)
    assert a.iv != b.iv, "IV was reused - catastrophic for GCM"
    assert a.ciphertext != b.ciphertext
    assert len(a.iv) == 12


def test_ciphertext_does_not_contain_plaintext():
    blob = encrypt_token(SECRET_TOKEN)
    assert SECRET_TOKEN.encode() not in blob.ciphertext


def test_tampered_ciphertext_is_rejected():
    blob = encrypt_token(SECRET_TOKEN)
    tampered = bytes([blob.ciphertext[0] ^ 0xFF]) + blob.ciphertext[1:]
    with pytest.raises(DecryptionError):
        decrypt_token(tampered, blob.iv)


def test_plaintext_token_absent_from_sqlite_file_bytes(db_session, app_db):
    """The single most important assertion: grep the DB file for the secret."""
    blob = encrypt_token(SECRET_TOKEN)
    db_session.add(
        PlatformToken(
            platform="instagram", encrypted_token=blob.ciphertext, iv=blob.iv
        )
    )
    db_session.commit()

    url = os.environ["DATABASE_URL"]
    db_path = Path(url.replace("sqlite:///", ""))
    raw = db_path.read_bytes()

    assert SECRET_TOKEN.encode() not in raw, "plaintext token found in the sqlite file"
    assert blob.ciphertext in raw, "ciphertext was not actually persisted"


def test_token_value_never_logged(caplog, wired):
    """Authenticating must not emit the bearer token into the logs."""
    caplog.set_level(logging.DEBUG)
    publisher = wired.get("instagram")
    token = publisher.authenticate()
    assert token
    captured = "\n".join(r.getMessage() for r in caplog.records)
    assert token not in captured, "access token leaked into log output"


def test_token_repr_does_not_leak():
    blob = encrypt_token(SECRET_TOKEN)
    row = PlatformToken(
        platform="x", encrypted_token=blob.ciphertext, iv=blob.iv
    )
    assert SECRET_TOKEN not in repr(row)
    assert str(blob.ciphertext) not in repr(row)
