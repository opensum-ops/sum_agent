from __future__ import annotations

import base64

import pytest
from nacl.signing import SigningKey

from sum_agent.core.canonical import canonical_bytes
from sum_agent.core.errors import SignatureError
from sum_agent.core.verify import verify_ed25519
from sum_agent.jobs import verify as jobs_verify


def test_verify_ed25519_round_trip() -> None:
    sk = SigningKey.generate()
    msg = b"hello world"
    sig = sk.sign(msg).signature
    assert verify_ed25519(bytes(sk.verify_key), msg, sig)
    assert not verify_ed25519(bytes(sk.verify_key), msg + b"!", sig)


def test_jobs_verify_happy_path() -> None:
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "server_id": "22222222-2222-2222-2222-222222222222",
        "capability": "rename_nic",
        "payload": {"current_name": "eth0", "new_name": "ens1"},
        "expires_at": "2026-05-17T12:00:00+00:00",
        "nonce": "AAECAw==",
    }
    sig = sk.sign(canonical_bytes(payload)).signature
    job = {**payload, "signature": base64.b64encode(sig).decode()}
    jobs_verify.verify(job, server_public_key_b64=pub_b64)  # must not raise


def test_jobs_verify_tampered_payload_raises() -> None:
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    payload = {
        "id": "11111111-1111-1111-1111-111111111111",
        "server_id": "22222222-2222-2222-2222-222222222222",
        "capability": "rename_nic",
        "payload": {"current_name": "eth0", "new_name": "ens1"},
        "expires_at": "2026-05-17T12:00:00+00:00",
        "nonce": "AAECAw==",
    }
    sig = sk.sign(canonical_bytes(payload)).signature
    tampered = {
        **payload,
        "payload": {"current_name": "eth0", "new_name": "EVIL"},
        "signature": base64.b64encode(sig).decode(),
    }
    with pytest.raises(SignatureError):
        jobs_verify.verify(tampered, server_public_key_b64=pub_b64)
