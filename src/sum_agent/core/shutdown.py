"""Classify why the agent is stopping: reboot, power-off, or plain stop.

On SIGTERM during a system shutdown, systemd has already queued the target
job, so ``systemctl list-jobs`` names it. A plain ``systemctl stop sum-agent``
(or a non-systemd host) shows no shutdown target and classifies as
``agent_stop``. Best-effort by design: any failure means ``agent_stop``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

# Values match the server's HeartbeatRequest.detail literals.
REBOOTING = "rebooting"
POWERED_OFF = "powered_off"
AGENT_STOP = "agent_stop"


def _run_list_jobs() -> str:
    binary = shutil.which("systemctl")
    if binary is None:
        return ""
    proc = subprocess.run(
        [binary, "list-jobs", "--no-legend", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return proc.stdout


def classify_shutdown(*, list_jobs: Callable[[], str] = _run_list_jobs) -> str:
    try:
        out = list_jobs()
    except (OSError, subprocess.TimeoutExpired):
        return AGENT_STOP
    if "reboot.target" in out:
        return REBOOTING
    if "poweroff.target" in out or "halt.target" in out:
        return POWERED_OFF
    return AGENT_STOP
