"""Agent self-reporting facts."""

from __future__ import annotations

from typing import Any

from sum_agent import __version__
from sum_agent.inventory.base import register


def collect() -> dict[str, Any]:
    return {"agent_version": __version__}


register("facts_agent", "facts", collect)
