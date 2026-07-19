"""Ed25519 verification via PyNaCl."""

from __future__ import annotations

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


def verify_ed25519(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return True iff ``signature`` is a valid Ed25519 signature for ``message``."""
    if len(public_key) != 32:
        return False
    if len(signature) != 64:
        return False
    try:
        VerifyKey(public_key).verify(message, signature)
    except BadSignatureError:
        return False
    return True
