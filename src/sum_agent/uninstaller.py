"""Agent self-uninstall: verify a server-signed directive, then remove itself.

Pull-based like everything else: the directive arrives on a heartbeat response
and is verified against the enrolled server public key before anything is
touched. An unsigned removal would be a fleet-wide kill switch, so an
unverifiable directive is ignored rather than acted on.

The hard part is that a running systemd service cannot delete its own unit and
binary. Self-update solved the adjacent problem with an atomic swap plus
``os.execv``; removal has nothing to exec into, so the cleanup has to *outlive*
this process. It runs in a `systemd-run` transient unit, the same mechanism the
server's own updater uses for the restart it cannot survive.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import structlog

from sum_agent.core import canonical, verify
from sum_agent.core.state import State
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)

# Must match sum_server.updates.directive.REMOVE_ACTION.
REMOVE_ACTION = "remove_agent"

# Transient unit name for the detached cleanup. Fixed, so a second attempt
# collides with the first rather than spawning a race over the same files.
CLEANUP_UNIT = "sum-agent-uninstall"


def current_binary() -> Path | None:
    """The running binary when frozen (PyInstaller), else ``None``.

    Removal only makes sense for the frozen single-file binary the installer
    put in place. Running from source there is no binary of ours to delete and
    no unit we own, so the directive is a no-op with a logged reason.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return None


def verify_directive(state: State, directive: dict[str, Any]) -> bool:
    """True if the directive is signed by the enrolled server key for this host.

    ``action`` is part of the signed payload, so an update directive's
    signature cannot be replayed as a removal, and ``requested_at`` binds it to
    one request rather than being replayable at this host forever.
    """
    try:
        payload = {
            "host_id": str(state.host_id),
            "action": directive["action"],
            "requested_at": directive["requested_at"],
        }
        pubkey = base64.b64decode(state.signing_public_key_b64)
        sig = base64.b64decode(directive["signature"])
    except (KeyError, ValueError, TypeError):
        return False
    if directive.get("action") != REMOVE_ACTION:
        return False
    return verify.verify_ed25519(pubkey, canonical.canonical_bytes(payload), sig)


def build_cleanup_script(*, binary: Path, settings: Settings) -> str:
    """The shell the detached unit runs.

    ``|| true`` throughout, and ordered so the service is stopped before the
    files it uses are removed. Every step is "make sure this is gone", so a
    piece already missing is success. Deliberately mirrors the server's
    ``uninstall.sh``: the two are the same contract about what lives where.
    """
    unit = settings.unit_path
    env_file = settings.env_file
    return "\n".join(
        [
            "set -u",
            # Stopping the service kills the agent that spawned this. That is
            # why it runs in its own transient unit rather than as a child.
            f"systemctl disable --now {settings.service_name} 2>/dev/null || true",
            f"rm -f {unit} || true",
            "systemctl daemon-reload 2>/dev/null || true",
            f"systemctl reset-failed {settings.service_name} 2>/dev/null || true",
            f"rm -f {env_file} || true",
            f"rmdir {Path(env_file).parent} 2>/dev/null || true",
            f"rm -rf {settings.state_dir} || true",
            # The binary last: everything above is described by paths, but this
            # is the file the running process was executed from.
            f"rm -f {binary} || true",
        ]
    )


def spawn_cleanup(*, binary: Path, settings: Settings) -> bool:
    """Launch the detached cleanup. True if it was handed off to systemd.

    A plain child process would not do: it lives in this service's cgroup, so
    stopping the service takes the cleanup with it. ``--collect`` reaps the
    transient unit once it exits so a removed host leaves no failed unit
    behind on the (now agentless) machine.
    """
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        log.error("uninstall_no_systemd_run")
        return False
    script = build_cleanup_script(binary=binary, settings=settings)
    try:
        # Fixed argv; the script is built from our own settings, never input.
        proc = subprocess.run(
            [
                systemd_run,
                f"--unit={CLEANUP_UNIT}",
                "--collect",
                "--description=Remove the OpenSUM agent",
                "/bin/sh",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("uninstall_spawn_failed", error=str(exc))
        return False
    if proc.returncode != 0:
        log.error("uninstall_spawn_failed", returncode=proc.returncode, stderr=proc.stderr.strip())
        return False
    log.info("uninstall_cleanup_spawned", unit=CLEANUP_UNIT)
    return True


def apply(state: State, directive: dict[str, Any], *, settings: Settings) -> bool:
    """Verify and hand off. True if cleanup is now running and we should exit.

    The caller sends the goodbye *before* calling this: once the cleanup starts
    the service is stopped, and a report that never left is the difference
    between the server knowing this host is clean and waiting on it forever.
    """
    if not verify_directive(state, directive):
        log.warning("uninstall_directive_invalid")
        return False
    binary = current_binary()
    if binary is None:
        log.warning("uninstall_skipped_not_frozen")
        return False
    return spawn_cleanup(binary=binary, settings=settings)
