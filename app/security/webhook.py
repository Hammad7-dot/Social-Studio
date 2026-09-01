"""HMAC-SHA256 webhook signing and constant-time verification."""
from __future__ import annotations

import hashlib
import hmac

from app.config import get_settings

SIGNATURE_HEADER = "X-Signature"
SIGNATURE_PREFIX = "sha256="


def sign(body: bytes, secret: str | None = None) -> str:
    secret = secret if secret is not None else get_settings().webhook_secret
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify(body: bytes, signature: str | None, secret: str | None = None) -> bool:
    """Constant-time comparison over the RAW request body."""
    if not signature:
        return False
    expected = sign(body, secret)
    # hmac.compare_digest is constant-time for equal-length inputs and does not
    # short-circuit on the first differing byte.
    return hmac.compare_digest(expected, signature)
