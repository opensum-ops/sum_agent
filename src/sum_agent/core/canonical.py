"""Canonical bytes for Ed25519 verification.

Exact mirror of ``sum_server.core.security.signing.canonical_bytes``. Kept
(with the verify helpers) even though signed job dispatch is removed: the
enroll response still delivers the server's public key, and signed work will
return on top of the inventory model. The format is pinned by
``tests/unit/test_signature_verify.py``; if the two sides ever drift,
verification fails at runtime.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, ASCII only."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
