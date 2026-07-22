from __future__ import annotations

import asyncio
import base64
from typing import Any

from nacl.signing import SigningKey

from sum_agent.core.canonical import canonical_bytes
from sum_agent.jobs import dispatch
from sum_agent.jobs.registry import Registry, registry


def _signed_job(sk: SigningKey, *, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "server_id": "22222222-2222-2222-2222-222222222222",
        "capability": capability,
        "payload": payload,
        "expires_at": "2026-05-17T12:00:00+00:00",
        "nonce": "AAECAw==",
    }
    sig = sk.sign(canonical_bytes(base)).signature
    return {**base, "signature": base64.b64encode(sig).decode()}


def _reset_registry() -> Registry:
    reg = registry()
    reg._handlers.clear()
    return reg


async def test_unknown_capability() -> None:
    _reset_registry()
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    job = _signed_job(sk, capability="nope", payload={})
    out = await dispatch.execute(job, server_public_key_b64=pub_b64, timeout_seconds=5)
    assert out["status"] == "failed"
    assert out["output"]["error"] == "unknown_capability"


async def test_signature_invalid() -> None:
    _reset_registry()
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    job = _signed_job(sk, capability="x", payload={"a": 1})
    job["payload"] = {"a": 2}  # tamper
    out = await dispatch.execute(job, server_public_key_b64=pub_b64, timeout_seconds=5)
    assert out["status"] == "failed"
    assert out["output"]["error"] == "signature_invalid"


async def test_happy_path_handler_completes() -> None:
    reg = _reset_registry()

    async def _ok(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "exit_code": 0, "output": {"echo": payload}}

    reg.register("ok", _ok)
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    job = _signed_job(sk, capability="ok", payload={"k": "v"})
    out = await dispatch.execute(job, server_public_key_b64=pub_b64, timeout_seconds=5)
    assert out["status"] == "completed"
    assert out["output"] == {"echo": {"k": "v"}}


async def test_handler_timeout() -> None:
    reg = _reset_registry()

    async def _slow(_p: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(5)
        return {"status": "completed", "exit_code": 0, "output": {}}

    reg.register("slow", _slow)
    sk = SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    job = _signed_job(sk, capability="slow", payload={})
    out = await dispatch.execute(job, server_public_key_b64=pub_b64, timeout_seconds=1)
    assert out["status"] == "failed"
    assert out["output"]["error"] == "timeout"
