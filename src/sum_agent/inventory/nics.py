"""NIC inventory collector (Linux). Reads ``/sys/class/net``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SYS_NET = Path("/sys/class/net")
_VIRTUAL_PREFIXES = ("docker", "veth", "br-", "tun", "tap", "virbr")
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


def _is_virtual(name: str) -> bool:
    if name == "lo":
        return True
    return any(name.startswith(p) for p in _VIRTUAL_PREFIXES)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _driver_for(iface_dir: Path) -> str | None:
    drv_link = iface_dir / "device" / "driver"
    try:
        if drv_link.is_symlink():
            return drv_link.resolve().name
    except OSError:
        return None
    return None


def collect(*, sys_net: Path = SYS_NET) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not sys_net.exists():
        return out
    for iface in sorted(sys_net.iterdir()):
        name = iface.name
        if _is_virtual(name):
            continue
        mac = _read(iface / "address") or ""
        if not _MAC_RE.fullmatch(mac):
            continue
        speed_raw = _read(iface / "speed")
        try:
            speed_mbps = max(int(speed_raw or "0"), 0)
        except ValueError:
            speed_mbps = 0
        driver = _driver_for(iface)
        out.append(
            {
                "kind": "nic",
                "vendor": None,
                "model": None,
                "serial": mac.lower(),
                "slot": name,
                "attrs": {
                    "kind": "nic",
                    "mac": mac.lower(),
                    "speed_mbps": speed_mbps,
                    "driver": driver,
                    "pci_addr": None,
                },
            }
        )
    return out
