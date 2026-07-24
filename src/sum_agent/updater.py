"""Agent self-update: verify a server-signed directive, swap the binary, and
fail over to the previous binary if the new one can't establish itself.

Pull-based: the directive arrives on a heartbeat response; the binary is pulled
from the server (never GitHub). The directive signature (over
``{host_id, target_version, sha256}``) is verified against the enrolled server
public key, the download is checked against the signed sha256, and the new
binary must pass a ``version`` smoke test before it is swapped in.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import structlog

from sum_agent import __version__, client
from sum_agent.core import canonical, verify
from sum_agent.core import state as state_mod
from sum_agent.core.errors import UpdateError
from sum_agent.core.state import PendingVerify, State
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)


def current_binary() -> Path | None:
    """The running binary path when frozen (PyInstaller), else ``None``.

    Self-update only makes sense for a frozen single-file binary; running from
    source (``uv run``) returns ``None`` and updates are skipped.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_directive(state: State, directive: dict[str, Any]) -> bool:
    """True if the directive is signed by the enrolled server key for this host."""
    payload = {
        "host_id": str(state.host_id),
        "target_version": directive["target_version"],
        "sha256": directive["sha256"],
    }
    try:
        pubkey = base64.b64decode(state.signing_public_key_b64)
        sig = base64.b64decode(directive["signature"])
    except (KeyError, ValueError):
        return False
    return verify.verify_ed25519(pubkey, canonical.canonical_bytes(payload), sig)


def _smoke_test(binary: Path, expected_version: str) -> bool:
    """Run ``<binary> version``; must exit 0 and print the target version."""
    try:
        proc = subprocess.run(
            [str(binary), "version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == expected_version


async def stage_binary(
    state: State, directive: dict[str, Any], *, settings: Settings, near: Path
) -> Path:
    """Download, checksum-verify, and smoke-test the new binary.

    Returns the staged temp path (in ``near``'s directory). Raises
    :class:`UpdateError` on any failure without touching the live binary.
    """
    target = directive["target_version"]
    fd, tmp_name = tempfile.mkstemp(prefix=".sum-agent-new-", dir=str(near.parent))
    os.close(fd)
    staged = Path(tmp_name)
    try:
        await client.download_binary(state, directive["binary_url"], staged, settings=settings)
    except Exception as exc:
        staged.unlink(missing_ok=True)
        raise UpdateError(f"download failed: {exc}") from exc

    actual = _sha256_file(staged)
    if actual != directive["sha256"]:
        staged.unlink(missing_ok=True)
        raise UpdateError(f"sha256 mismatch: expected {directive['sha256']}, got {actual}")

    staged.chmod(0o755)
    if not _smoke_test(staged, target):
        staged.unlink(missing_ok=True)
        raise UpdateError(f"smoke test failed for {target}")
    return staged


def swap_in(*, current: Path, staged: Path, state: State, settings: Settings, target: str) -> None:
    """Back up the current binary, move the new one into place, and persist
    ``pending_verify`` (everything up to, but not including, the re-exec).
    """
    backup = current.with_suffix(".bak")
    shutil.copy2(current, backup)
    os.replace(staged, current)
    deadline = dt.datetime.now(tz=dt.UTC) + dt.timedelta(
        seconds=settings.self_update_verify_seconds
    )
    state.pending_verify = PendingVerify(
        target_version=target, previous_binary=str(backup), deadline=deadline
    )
    state_mod.save(settings.state_dir, state)


async def apply(state: State, directive: dict[str, Any], *, settings: Settings) -> None:
    """Verify + stage + swap + re-exec into the new binary. Does not return on
    success (``execv`` replaces the process).
    """
    current = current_binary()
    if current is None:
        log.info("self_update_skipped_not_frozen")
        return
    if not verify_directive(state, directive):
        raise UpdateError("directive signature invalid")

    target = directive["target_version"]
    log.info("self_update_starting", target=target, current=__version__)
    staged = await stage_binary(state, directive, settings=settings, near=current)
    swap_in(current=current, staged=staged, state=state, settings=settings, target=target)
    log.info("self_update_swapped", target=target)
    os.execv(str(current), [str(current), "run"])


def confirm(state: State, *, settings: Settings) -> None:
    """Mark a pending update as successful: clear state and drop the backup."""
    pending = state.pending_verify
    if pending is None:
        return
    state.pending_verify = None
    state_mod.save(settings.state_dir, state)
    with contextlib.suppress(OSError):
        Path(pending.previous_binary).unlink(missing_ok=True)
    log.info("self_update_confirmed", version=__version__)


def revert(state: State, *, settings: Settings) -> None:
    """Restore the previous binary and re-exec into it (failover)."""
    pending = state.pending_verify
    if pending is None:
        return
    current = current_binary()
    backup = Path(pending.previous_binary)
    log.warning("self_update_reverting", target=pending.target_version)
    state.pending_verify = None
    state_mod.save(settings.state_dir, state)
    if current is not None and backup.exists():
        os.replace(backup, current)
        os.execv(str(current), [str(current), "run"])


def has_expired(pending: PendingVerify, *, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(tz=dt.UTC)
    return now >= pending.deadline
