"""Job signature verification."""

from __future__ import annotations

import base64
from typing import Any

from sum_agent.core.canonical import build_job_signing_payload, canonical_bytes
from sum_agent.core.errors import SignatureError
from sum_agent.core.verify import verify_ed25519


def verify(job: dict[str, Any], *, server_public_key_b64: str) -> None:
    """Verify the Ed25519 signature on a server ``JobResponse`` dict.

    Raises :class:`SignatureError` on mismatch. ``signature`` and ``nonce`` are
    base64-encoded on the wire; everything else flows through canonicalization.
    """
    pub = base64.b64decode(server_public_key_b64)
    sig = base64.b64decode(job["signature"])
    payload = build_job_signing_payload(job)
    message = canonical_bytes(payload)
    if not verify_ed25519(pub, message, sig):
        raise SignatureError(f"signature did not verify for job {job.get('id')}")
