"""OS + kernel facts: ``/etc/os-release`` and ``uname``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sum_agent.inventory.base import register

OS_RELEASE = Path("/etc/os-release")


def parse_os_release(text: str) -> dict[str, str]:
    """Parse the ``KEY=value`` / ``KEY="value"`` lines of os-release."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key] = value.strip().strip('"')
    return out


def collect(*, os_release: Path = OS_RELEASE) -> dict[str, Any]:
    facts: dict[str, Any] = {"kernel": os.uname().release}
    try:
        fields = parse_os_release(os_release.read_text(encoding="utf-8"))
    except OSError:
        return facts
    if "ID" in fields:
        facts["os_id"] = fields["ID"]
    if "NAME" in fields:
        facts["os_name"] = fields["NAME"]
    if "VERSION_ID" in fields:
        facts["os_version"] = fields["VERSION_ID"]
    return facts


register("facts_os", "facts", collect)
