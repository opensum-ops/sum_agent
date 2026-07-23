"""CPU inventory collector (Linux). Parses /proc/cpuinfo with psutil fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psutil

from sum_agent.inventory.base import register

CPUINFO_PATH = Path("/proc/cpuinfo")


def _flush(current: dict[str, str], sockets: dict[str, dict[str, Any]]) -> None:
    if not current:
        return
    phys = current.get("physical id", "0")
    entry = sockets.setdefault(
        phys,
        {
            "vendor": current.get("vendor_id"),
            "model": current.get("model name"),
            "threads": 0,
            "cores": 0,
            "max_mhz": 0.0,
        },
    )
    entry["threads"] += 1
    cores = int(current.get("cpu cores", "0") or "0")
    if cores > entry["cores"]:
        entry["cores"] = cores
    try:
        mhz = float(current.get("cpu MHz", "0") or "0")
    except ValueError:
        mhz = 0.0
    if mhz > entry["max_mhz"]:
        entry["max_mhz"] = mhz


def _parse_cpuinfo(text: str) -> dict[str, dict[str, Any]]:
    sockets: dict[str, dict[str, Any]] = {}
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            _flush(current, sockets)
            current = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            current[k.strip()] = v.strip()
    _flush(current, sockets)
    return sockets


def collect(*, cpuinfo: str | None = None) -> list[dict[str, Any]]:
    """Return ``ComponentIngest`` dicts for each physical CPU socket."""
    if cpuinfo is None:
        if not CPUINFO_PATH.exists():
            cpuinfo = ""
        else:
            cpuinfo = CPUINFO_PATH.read_text(encoding="utf-8", errors="replace")

    sockets = _parse_cpuinfo(cpuinfo) if cpuinfo else {}
    if not sockets:
        try:
            freq = psutil.cpu_freq()
            max_hz = int((freq.max or 0) * 1_000_000) if freq else 0
        except Exception:
            max_hz = 0
        cores = psutil.cpu_count(logical=False) or 1
        threads = psutil.cpu_count(logical=True) or cores
        return [
            {
                "kind": "cpu",
                "vendor": None,
                "model": None,
                "serial": "cpu-0",
                "slot": "cpu0",
                "attrs": {
                    "kind": "cpu",
                    "cores": cores,
                    "threads": threads,
                    "base_hz": max_hz,
                    "microarch": None,
                },
            }
        ]

    out: list[dict[str, Any]] = []
    for phys_id, info in sorted(
        sockets.items(),
        key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0,
    ):
        cores = info["cores"] or 1
        threads = info["threads"] or cores
        base_hz = int(info["max_mhz"] * 1_000_000) if info["max_mhz"] else 0
        out.append(
            {
                "kind": "cpu",
                "vendor": info["vendor"],
                "model": info["model"],
                "serial": f"cpu-{phys_id}",
                "slot": f"cpu{phys_id}",
                "attrs": {
                    "kind": "cpu",
                    "cores": cores,
                    "threads": threads,
                    "base_hz": base_hz,
                    "microarch": None,
                },
            }
        )
    return out


register("cpu", "components", collect)
