"""Pin the canonical-bytes contract.

The bytes the agent generates from a sample Job must match what sum_server signs.
The expected bytes here were computed against ``sum_server.core.security.signing``
for the fixture below. If this test fails, signature verification will fail at
runtime — fix the divergence immediately.
"""

from __future__ import annotations

from sum_agent.core.canonical import build_job_signing_payload, canonical_bytes


def test_canonical_bytes_sample() -> None:
    job = {
        "id": "11111111-1111-1111-1111-111111111111",
        "server_id": "22222222-2222-2222-2222-222222222222",
        "capability": "rename_nic",
        "payload": {"current_name": "eth0", "new_name": "ens1"},
        "expires_at": "2026-05-17T12:00:00+00:00",
        "nonce": "AAECAwQFBgcICQoLDA0ODw==",
        "signature": "ignored-for-canonicalization",
    }
    payload = build_job_signing_payload(job)
    out = canonical_bytes(payload)
    expected = (
        b'{"capability":"rename_nic",'
        b'"expires_at":"2026-05-17T12:00:00+00:00",'
        b'"id":"11111111-1111-1111-1111-111111111111",'
        b'"nonce":"AAECAwQFBgcICQoLDA0ODw==",'
        b'"payload":{"current_name":"eth0","new_name":"ens1"},'
        b'"server_id":"22222222-2222-2222-2222-222222222222"}'
    )
    assert out == expected


def test_microseconds_are_stripped() -> None:
    payload = build_job_signing_payload(
        {
            "id": "1" * 32,
            "server_id": "2" * 32,
            "capability": "x",
            "payload": {},
            "expires_at": "2026-05-17T12:00:00.123456+00:00",
            "nonce": "AAAA",
        }
    )
    assert payload["expires_at"] == "2026-05-17T12:00:00+00:00"
