"""Disk inventory collector (Linux). Shells out to ``lsblk -J``."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sum_agent.inventory.base import register

_LSBLK_CMD = (
    "lsblk",
    "-J",
    "-d",
    "-b",
    "-o",
    "NAME,VENDOR,MODEL,SERIAL,SIZE,ROTA,TYPE,TRAN,WWN",
)

_BUS_MAP = {
    "sata": "sata",
    "nvme": "nvme",
    "sas": "sas",
    "usb": "usb",
    "scsi": "scsi",
}


async def _run_lsblk() -> str:
    proc = await asyncio.create_subprocess_exec(
        *_LSBLK_CMD,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"lsblk failed: {err.decode(errors='replace')}")
    return out.decode(errors="replace")


def parse(json_text: str) -> list[dict[str, Any]]:
    """Parse an ``lsblk -J`` document into ``ComponentIngest`` dicts."""
    data = json.loads(json_text)
    out: list[dict[str, Any]] = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        name = d.get("name") or ""
        bus_raw = (d.get("tran") or "").lower()
        bus = _BUS_MAP.get(bus_raw, "unknown")
        rota = d.get("rota")
        rotation = 7200 if rota in (1, True, "1") else 0
        try:
            size = int(d.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        serial = (d.get("serial") or "").strip() or None
        wwn = (d.get("wwn") or "").strip() or None
        out.append(
            {
                "kind": "disk",
                "vendor": (d.get("vendor") or "").strip() or None,
                "model": (d.get("model") or "").strip() or None,
                "serial": serial,
                "slot": name or None,
                "attrs": {
                    "kind": "disk",
                    "size_bytes": size,
                    "rotation_rpm": rotation,
                    "bus": bus,
                    "wwn": wwn,
                },
            }
        )
    return out


async def collect() -> list[dict[str, Any]]:
    text = await _run_lsblk()
    return parse(text)


register("disks", "components", collect)
