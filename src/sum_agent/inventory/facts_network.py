"""Network addressing facts: default interface + primary addresses.

The default IPv4 interface comes from ``/proc/net/route`` (destination
``00000000``); addresses come from psutil for that interface.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from sum_agent.inventory.base import register

PROC_ROUTE = Path("/proc/net/route")


def default_iface_from_route(text: str) -> str | None:
    for line in text.splitlines()[1:]:
        fields = line.split()
        # Iface Destination Gateway Flags ... ; default route has dest 0.
        if len(fields) >= 2 and fields[1] == "00000000":
            return fields[0]
    return None


def collect(
    *,
    route_path: Path = PROC_ROUTE,
    if_addrs: Callable[[], dict[str, list[Any]]] = psutil.net_if_addrs,
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    try:
        iface = default_iface_from_route(route_path.read_text(encoding="utf-8"))
    except OSError:
        iface = None
    if iface is None:
        return facts
    facts["default_iface"] = iface

    for addr in if_addrs().get(iface, []):
        if addr.family == socket.AF_INET and "primary_ipv4" not in facts:
            facts["primary_ipv4"] = addr.address
        elif addr.family == socket.AF_INET6 and "primary_ipv6" not in facts:
            # Skip link-local; strip any %scope suffix.
            address = addr.address.split("%", 1)[0]
            if not address.lower().startswith("fe80"):
                facts["primary_ipv6"] = address
    return facts


register("facts_network", "facts", collect)
