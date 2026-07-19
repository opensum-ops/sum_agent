"""Canonical bytes for Ed25519 verification.

Exact mirror of ``sum_server.core.security.signing.canonical_bytes`` and the
``_signing_payload`` shape. The agent reconstructs this from a server
``JobResponse`` dict before verifying.

If the two ever drift, signature verification will fail at runtime, so
``tests/unit/test_canonical_matches_server.py`` pins this with a hardcoded
fixture matching the server.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, ASCII only."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def build_job_signing_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct the dict the server signed from a ``JobResponse``.

    The server signs ``{id, server_id, capability, payload, nonce, expires_at}``
    with timestamps formatted as ``replace(microsecond=0).isoformat()``. We
    apply the same normalization here.
    """
    expires_at = job["expires_at"]
    if isinstance(expires_at, str):
        # Parse to datetime, drop microseconds, re-isoformat to match server.
        parsed = dt.datetime.fromisoformat(expires_at)
        expires_at = parsed.replace(microsecond=0).isoformat()
    elif isinstance(expires_at, dt.datetime):
        expires_at = expires_at.replace(microsecond=0).isoformat()
    else:
        raise TypeError(f"unexpected expires_at type: {type(expires_at)!r}")

    return {
        "id": str(job["id"]),
        "server_id": str(job["server_id"]),
        "capability": job["capability"],
        "payload": job["payload"],
        "nonce": job["nonce"],  # already a base64 string on the wire
        "expires_at": expires_at,
    }
