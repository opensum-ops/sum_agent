"""Memory inventory collector (Linux). Total via psutil; DIMM detail deferred."""

from __future__ import annotations

from typing import Any

import psutil


def collect() -> list[dict[str, Any]]:
    total = int(psutil.virtual_memory().total)
    return [
        {
            "kind": "memory",
            "vendor": None,
            "model": None,
            "serial": None,
            "slot": "system",
            "attrs": {
                "kind": "memory",
                "size_bytes": total,
                "speed_mts": 0,
                "form_factor": None,
                "slot": "system",
            },
        }
    ]
