"""``rename_nic`` capability: rename an interface via iproute2."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sum_agent.jobs.registry import JobOutcome, register_builtin

SYS_NET = Path("/sys/class/net")


async def _ip(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "ip",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return (
        proc.returncode or 0,
        out_b.decode(errors="replace"),
        err_b.decode(errors="replace"),
    )


@register_builtin("rename_nic")
async def handle(payload: dict[str, Any]) -> JobOutcome:
    current = payload.get("current_name")
    new = payload.get("new_name")
    if not current or not new:
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "missing current_name or new_name"},
        }

    if not (SYS_NET / current).exists():
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "interface_not_found", "interface": current},
        }
    if (SYS_NET / new).exists():
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "new_name_exists", "interface": new},
        }

    stages: list[tuple[str, tuple[str, ...]]] = [
        ("down", ("link", "set", current, "down")),
        ("rename", ("link", "set", current, "name", new)),
        ("up", ("link", "set", new, "up")),
    ]
    for stage, cmd in stages:
        rc, _out, err = await _ip(*cmd)
        if rc != 0:
            return {
                "status": "failed",
                "exit_code": rc,
                "output": {
                    "error": "ip_link_failed",
                    "stage": stage,
                    "stderr": err.strip(),
                },
            }

    return {
        "status": "completed",
        "exit_code": 0,
        "output": {"from": current, "to": new},
    }
