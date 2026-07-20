"""``mount_disk`` capability: mount + idempotent ``/etc/fstab`` entry."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from sum_agent.jobs.registry import JobOutcome, register_builtin

FSTAB = Path("/etc/fstab")


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return (
        proc.returncode or 0,
        out_b.decode(errors="replace"),
        err_b.decode(errors="replace"),
    )


def _fstab_has_mountpoint(text: str, mountpoint: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == mountpoint:
            return True
    return False


def _ensure_fstab(device: str, mountpoint: str, fstype: str, options: str) -> bool:
    if not FSTAB.exists():
        return False
    current = FSTAB.read_text(encoding="utf-8")
    if _fstab_has_mountpoint(current, mountpoint):
        return False
    line = f"{device}\t{mountpoint}\t{fstype}\t{options}\t0\t2\n"
    with FSTAB.open("a", encoding="utf-8") as f:
        f.write(line)
    return True


@register_builtin("mount_disk")
async def handle(payload: dict[str, Any]) -> JobOutcome:
    device = payload.get("device")
    mountpoint = payload.get("mountpoint")
    fstype = payload.get("fstype")
    options = payload.get("options", "defaults")
    if not (device and mountpoint and fstype):
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "missing device, mountpoint, or fstype"},
        }

    try:
        os.makedirs(mountpoint, exist_ok=True)
    except OSError as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "mkdir_failed", "stderr": str(exc)},
        }

    rc, _out, err = await _run(["mount", "-t", fstype, "-o", options, device, mountpoint])
    if rc != 0:
        return {
            "status": "failed",
            "exit_code": rc,
            "output": {"error": "mount_failed", "stderr": err.strip()},
        }

    try:
        fstab_added = _ensure_fstab(device, mountpoint, fstype, options)
        return {
            "status": "completed",
            "exit_code": 0,
            "output": {
                "device": device,
                "mountpoint": mountpoint,
                "fstab_added": fstab_added,
            },
        }
    except OSError as exc:
        return {
            "status": "completed",
            "exit_code": 0,
            "output": {
                "device": device,
                "mountpoint": mountpoint,
                "fstab_added": False,
                "fstab_error": str(exc),
            },
        }
