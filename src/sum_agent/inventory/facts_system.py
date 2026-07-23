"""System identity facts: hostname, machine/boot ids, arch, virtualization."""

from __future__ import annotations

import datetime as dt
import platform
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

import psutil

from sum_agent.inventory.base import register

MACHINE_ID = Path("/etc/machine-id")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def read_boot_id(*, boot_id_path: Path = BOOT_ID) -> str | None:
    """Kernel boot id; also sent with every heartbeat for crash detection."""
    return _read(boot_id_path)


def detect_virtualization() -> str | None:
    """Best-effort ``systemd-detect-virt``; ``"none"`` on bare metal."""
    binary = shutil.which("systemd-detect-virt")
    if binary is None:
        return None
    try:
        proc = subprocess.run([binary], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = proc.stdout.strip()
    # rc 0 = virtualized (prints the kind); rc 1 prints "none" on bare metal.
    return out or None


def collect(
    *,
    machine_id_path: Path = MACHINE_ID,
    boot_id_path: Path = BOOT_ID,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "arch": platform.machine(),
        "boot_time": dt.datetime.fromtimestamp(psutil.boot_time(), tz=dt.UTC).isoformat(),
    }
    fqdn = socket.getfqdn()
    if fqdn and fqdn != facts["hostname"]:
        facts["fqdn"] = fqdn
    if (machine_id := _read(machine_id_path)) is not None:
        facts["machine_id"] = machine_id
    if (boot_id := read_boot_id(boot_id_path=boot_id_path)) is not None:
        facts["boot_id"] = boot_id
    if (virt := detect_virtualization()) is not None:
        facts["virtualization"] = virt
    return facts


register("facts_system", "facts", collect)
