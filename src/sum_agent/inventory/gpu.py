"""GPU inventory collector (Linux). Best-effort via lspci + nvidia-smi."""

from __future__ import annotations

import asyncio
import shlex
import shutil
from typing import Any

from sum_agent.inventory.base import register


async def _maybe_run(*cmd: str) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        return out.decode(errors="replace")
    except OSError:
        return None


def _parse_lspci_mm(text: str) -> list[tuple[str, str, str]]:
    """Return ``(pci_addr, vendor, model)`` for VGA/3D/Display entries.

    ``lspci -mm`` quotes fields with embedded spaces. ``shlex.split`` handles
    that for us.
    """
    out: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 4:
            continue
        addr, cls, vendor, model = parts[0], parts[1], parts[2], parts[3]
        lc = cls.lower()
        if "vga" in lc or "3d" in lc or "display" in lc:
            out.append((addr, vendor, model))
    return out


async def collect() -> list[dict[str, Any]]:
    lspci = await _maybe_run("lspci", "-mm")
    if not lspci:
        return []
    gpus = _parse_lspci_mm(lspci)
    if not gpus:
        return []
    vram_bytes = 0
    nv = await _maybe_run("nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits")
    if nv:
        first = nv.strip().splitlines()[0].strip()
        try:
            vram_bytes = int(first) * 1024 * 1024
        except ValueError:
            vram_bytes = 0
    out: list[dict[str, Any]] = []
    for addr, vendor, model in gpus:
        out.append(
            {
                "kind": "gpu",
                "vendor": vendor or None,
                "model": model or None,
                "serial": None,
                "slot": addr,
                "attrs": {
                    "kind": "gpu",
                    "vram_bytes": vram_bytes,
                    "driver_version": None,
                    "pci_addr": addr,
                },
            }
        )
    return out


register("gpu", "components", collect)
