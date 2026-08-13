"""Agent self-uninstall: directive verification and the detached cleanup.

The signature checks matter most here. An unsigned or replayable removal
directive is a fleet-wide kill switch, so each way one could be forged gets a
test rather than a comment.
"""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import pytest
from nacl.signing import SigningKey

from sum_agent.core import canonical
from sum_agent.core.state import State
from sum_agent.settings import Settings

from sum_agent import uninstaller  # isort: skip


HOST_ID = uuid.uuid4()
REQUESTED_AT = "2026-08-11T12:00:00+00:00"


def _state(pubkey_b64: str) -> State:
    return State(
        server_url="https://sum.local",
        host_id=HOST_ID,
        agent_token="tok",
        signing_public_key_b64=pubkey_b64,
        enrolled_at=dt.datetime.now(tz=dt.UTC),
    )


def _signed(
    sk: SigningKey,
    *,
    host_id: uuid.UUID = HOST_ID,
    action: str = uninstaller.REMOVE_ACTION,
    requested_at: str = REQUESTED_AT,
) -> dict[str, str]:
    payload = {"host_id": str(host_id), "action": action, "requested_at": requested_at}
    sig = sk.sign(canonical.canonical_bytes(payload)).signature
    return {
        "action": action,
        "requested_at": requested_at,
        "signature": base64.b64encode(sig).decode(),
    }


@pytest.fixture
def keys() -> tuple[SigningKey, State]:
    sk = SigningKey.generate()
    return sk, _state(base64.b64encode(bytes(sk.verify_key)).decode())


# --- Verification -----------------------------------------------------------


def test_verifies_a_properly_signed_directive(keys: tuple[SigningKey, State]) -> None:
    sk, st = keys
    assert uninstaller.verify_directive(st, _signed(sk))


def test_rejects_a_directive_signed_for_another_host(keys: tuple[SigningKey, State]) -> None:
    """Otherwise one host's removal could be replayed across the fleet."""
    sk, st = keys
    assert not uninstaller.verify_directive(st, _signed(sk, host_id=uuid.uuid4()))


def test_rejects_a_directive_from_another_key(keys: tuple[SigningKey, State]) -> None:
    _sk, st = keys
    assert not uninstaller.verify_directive(st, _signed(SigningKey.generate()))


def test_rejects_a_tampered_timestamp(keys: tuple[SigningKey, State]) -> None:
    sk, st = keys
    d = _signed(sk)
    d["requested_at"] = "2026-09-01T00:00:00+00:00"
    assert not uninstaller.verify_directive(st, d)


def test_rejects_an_unexpected_action(keys: tuple[SigningKey, State]) -> None:
    """Signed by the right key for the right host, but not a removal."""
    sk, st = keys
    assert not uninstaller.verify_directive(st, _signed(sk, action="something_else"))


@pytest.mark.parametrize(
    "directive",
    [
        {},
        {"action": uninstaller.REMOVE_ACTION},
        {"action": uninstaller.REMOVE_ACTION, "requested_at": REQUESTED_AT},
        {"action": uninstaller.REMOVE_ACTION, "requested_at": REQUESTED_AT, "signature": "!!!"},
    ],
)
def test_malformed_directives_are_refused_not_crashed(
    keys: tuple[SigningKey, State], directive: dict[str, Any]
) -> None:
    _sk, st = keys
    assert not uninstaller.verify_directive(st, directive)


# --- The cleanup script -----------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        server_url="https://sum.local",
        state_dir=tmp_path / "state",
        unit_path="/etc/systemd/system/sum-agent.service",
        env_file="/etc/sum-agent/agent.env",
        service_name="sum-agent",
    )


def test_cleanup_script_removes_everything_the_installer_placed(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    script = uninstaller.build_cleanup_script(binary=Path("/usr/local/bin/sum-agent"), settings=s)
    for path in (
        "/etc/systemd/system/sum-agent.service",
        "/etc/sum-agent/agent.env",
        str(tmp_path / "state"),
        "/usr/local/bin/sum-agent",
    ):
        assert path in script


def test_cleanup_script_stops_the_service_before_deleting_it(tmp_path: Path) -> None:
    """Order is load-bearing: the disable is what kills the agent that spawned
    this, and it has to happen before the unit file it refers to is gone."""
    script = uninstaller.build_cleanup_script(
        binary=Path("/usr/local/bin/sum-agent"), settings=_settings(tmp_path)
    )
    assert script.index("systemctl disable --now") < script.index("rm -f /etc/systemd/system")


def test_cleanup_script_is_valid_shell(tmp_path: Path) -> None:
    """It is executed by /bin/sh in a transient unit, where a syntax error
    would leave the agent half-removed with nothing reporting why."""
    import shutil
    import subprocess

    script = uninstaller.build_cleanup_script(
        binary=Path("/usr/local/bin/sum-agent"), settings=_settings(tmp_path)
    )
    sh = shutil.which("sh")
    assert sh is not None
    check = subprocess.run([sh, "-n"], input=script, text=True, capture_output=True, check=False)
    assert check.returncode == 0, check.stderr


def test_cleanup_script_tolerates_missing_pieces(tmp_path: Path) -> None:
    """Every step is "make sure this is gone", so a piece already missing is
    success. That is what makes a retried removal safe."""
    script = uninstaller.build_cleanup_script(
        binary=Path("/usr/local/bin/sum-agent"), settings=_settings(tmp_path)
    )
    for line in script.splitlines():
        if line.startswith(("rm ", "rmdir ", "systemctl ")):
            assert line.endswith("|| true"), line


# --- Handoff ----------------------------------------------------------------


def test_apply_refuses_an_invalid_directive(
    keys: tuple[SigningKey, State], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing may be spawned on the strength of a signature we could not check."""
    _sk, st = keys
    spawned = False

    def _spy(**_kw: Any) -> bool:
        nonlocal spawned
        spawned = True
        return True

    monkeypatch.setattr(uninstaller, "spawn_cleanup", _spy)
    monkeypatch.setattr(uninstaller, "current_binary", lambda: Path("/usr/local/bin/sum-agent"))
    assert not uninstaller.apply(st, _signed(SigningKey.generate()), settings=_settings(tmp_path))
    assert not spawned


def test_apply_is_a_no_op_from_source(
    keys: tuple[SigningKey, State], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running from source there is no binary of ours to delete."""
    sk, st = keys
    monkeypatch.setattr(uninstaller, "current_binary", lambda: None)
    monkeypatch.setattr(
        uninstaller, "spawn_cleanup", lambda **_kw: pytest.fail("must not spawn from source")
    )
    assert not uninstaller.apply(st, _signed(sk), settings=_settings(tmp_path))


def test_apply_hands_off_when_frozen_and_signed(
    keys: tuple[SigningKey, State], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sk, st = keys
    seen: dict[str, Any] = {}

    def _spy(*, binary: Path, settings: Settings) -> bool:
        seen["binary"] = binary
        return True

    monkeypatch.setattr(uninstaller, "current_binary", lambda: Path("/usr/local/bin/sum-agent"))
    monkeypatch.setattr(uninstaller, "spawn_cleanup", _spy)
    assert uninstaller.apply(st, _signed(sk), settings=_settings(tmp_path))
    assert seen["binary"] == Path("/usr/local/bin/sum-agent")


def test_spawn_reports_failure_when_systemd_run_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain child would be killed with the service, so without systemd-run
    there is no safe way to proceed and the agent stays put."""
    monkeypatch.setattr(uninstaller.shutil, "which", lambda _name: None)
    assert not uninstaller.spawn_cleanup(
        binary=Path("/usr/local/bin/sum-agent"), settings=_settings(tmp_path)
    )
