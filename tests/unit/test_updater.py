"""Agent self-update: directive verification, swap/revert/confirm state I/O."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import uuid
from pathlib import Path

import pytest
from nacl.signing import SigningKey

from sum_agent.core import canonical
from sum_agent.core.state import PendingVerify, State
from sum_agent.settings import Settings

from sum_agent import updater  # isort: skip


HOST_ID = uuid.uuid4()


def _state(pubkey_b64: str, state_dir: Path) -> State:
    return State(
        server_url="https://sum.local",
        host_id=HOST_ID,
        agent_token="tok",
        signing_public_key_b64=pubkey_b64,
        enrolled_at=dt.datetime.now(tz=dt.UTC),
    )


def _signed_directive(sk: SigningKey, target: str, sha: str, url: str) -> dict[str, str]:
    payload = {"host_id": str(HOST_ID), "target_version": target, "sha256": sha}
    sig = sk.sign(canonical.canonical_bytes(payload)).signature
    return {
        "target_version": target,
        "sha256": sha,
        "binary_url": url,
        "signature": base64.b64encode(sig).decode(),
    }


def test_verify_directive_good(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    st = _state(pub, tmp_path)
    d = _signed_directive(sk, "0.3.0", "abc", "https://sum.local/bin")
    assert updater.verify_directive(st, d)


def test_verify_directive_tampered(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    st = _state(pub, tmp_path)
    d = _signed_directive(sk, "0.3.0", "abc", "https://sum.local/bin")
    d["sha256"] = "deadbeef"  # break the binding
    assert not updater.verify_directive(st, d)


def test_verify_directive_wrong_key(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    other = base64.b64encode(bytes(SigningKey.generate().verify_key)).decode()
    st = _state(other, tmp_path)
    d = _signed_directive(sk, "0.3.0", "abc", "https://sum.local/bin")
    assert not updater.verify_directive(st, d)


def _settings(state_dir: Path) -> Settings:
    return Settings(server_url="https://sum.local", state_dir=state_dir)


def test_swap_in_backs_up_and_sets_pending(tmp_path: Path) -> None:
    current = tmp_path / "sum-agent"
    current.write_bytes(b"OLD")
    staged = tmp_path / ".staged"
    staged.write_bytes(b"NEW")
    st = _state("x", tmp_path)
    settings = _settings(tmp_path)

    updater.swap_in(current=current, staged=staged, state=st, settings=settings, target="0.3.0")

    assert current.read_bytes() == b"NEW"
    assert current.with_suffix(".bak").read_bytes() == b"OLD"
    assert st.pending_verify is not None
    assert st.pending_verify.target_version == "0.3.0"
    # Persisted to disk.
    from sum_agent.core import state as state_mod

    reloaded = state_mod.load(tmp_path)
    assert reloaded.pending_verify is not None


def test_confirm_clears_and_removes_backup(tmp_path: Path) -> None:
    current = tmp_path / "sum-agent"
    current.write_bytes(b"NEW")
    backup = current.with_suffix(".bak")
    backup.write_bytes(b"OLD")
    st = _state("x", tmp_path)
    st.pending_verify = PendingVerify(
        target_version="0.3.0",
        previous_binary=str(backup),
        deadline=dt.datetime.now(tz=dt.UTC),
    )
    settings = _settings(tmp_path)
    from sum_agent.core import state as state_mod

    state_mod.save(tmp_path, st)

    updater.confirm(st, settings=settings)
    assert st.pending_verify is None
    assert not backup.exists()
    assert state_mod.load(tmp_path).pending_verify is None


def test_has_expired() -> None:
    past = PendingVerify(
        target_version="0.3.0",
        previous_binary="/x",
        deadline=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
    )
    future = PendingVerify(
        target_version="0.3.0",
        previous_binary="/x",
        deadline=dt.datetime(2999, 1, 1, tzinfo=dt.UTC),
    )
    assert updater.has_expired(past)
    assert not updater.has_expired(future)


async def test_stage_binary_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    near = tmp_path / "sum-agent"
    near.write_bytes(b"cur")
    st = _state("x", tmp_path)
    settings = _settings(tmp_path)

    async def fake_download(_state: object, _url: str, dest: Path, *, settings: object) -> None:
        dest.write_bytes(b"downloaded-bytes")

    monkeypatch.setattr(updater.client, "download_binary", fake_download)
    directive = {
        "target_version": "0.3.0",
        "sha256": "0" * 64,  # deliberately wrong
        "binary_url": "https://sum.local/bin",
        "signature": "",
    }
    with pytest.raises(updater.UpdateError, match="sha256 mismatch"):
        await updater.stage_binary(st, directive, settings=settings, near=near)
    # nothing staged is left behind
    assert list(tmp_path.glob(".sum-agent-new-*")) == []


async def test_stage_binary_smoke_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    near = tmp_path / "sum-agent"
    near.write_bytes(b"cur")
    st = _state("x", tmp_path)
    settings = _settings(tmp_path)
    content = b"downloaded-bytes"
    sha = hashlib.sha256(content).hexdigest()

    async def fake_download(_state: object, _url: str, dest: Path, *, settings: object) -> None:
        dest.write_bytes(content)

    monkeypatch.setattr(updater.client, "download_binary", fake_download)
    monkeypatch.setattr(updater, "_smoke_test", lambda _b, _v: False)
    directive = {
        "target_version": "0.3.0",
        "sha256": sha,
        "binary_url": "https://sum.local/bin",
        "signature": "",
    }
    with pytest.raises(updater.UpdateError, match="smoke test failed"):
        await updater.stage_binary(st, directive, settings=settings, near=near)


async def test_stage_binary_happy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    near = tmp_path / "sum-agent"
    near.write_bytes(b"cur")
    st = _state("x", tmp_path)
    settings = _settings(tmp_path)
    content = b"downloaded-bytes"
    sha = hashlib.sha256(content).hexdigest()

    async def fake_download(_state: object, _url: str, dest: Path, *, settings: object) -> None:
        dest.write_bytes(content)

    monkeypatch.setattr(updater.client, "download_binary", fake_download)
    monkeypatch.setattr(updater, "_smoke_test", lambda _b, _v: True)
    directive = {
        "target_version": "0.3.0",
        "sha256": sha,
        "binary_url": "https://sum.local/bin",
        "signature": "",
    }
    staged = await updater.stage_binary(st, directive, settings=settings, near=near)
    assert staged.read_bytes() == content
    assert staged.stat().st_mode & 0o111  # executable
