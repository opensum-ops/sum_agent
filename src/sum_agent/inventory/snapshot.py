"""Orchestrator: build a full inventory snapshot from every registered collector.

Per-collector failures are caught, logged, and ignored: inventory is
best-effort and partial snapshots are preferable to none.
"""

from __future__ import annotations

from typing import Any

import structlog

from sum_agent.inventory.base import collectors, run_collector

log = structlog.get_logger(__name__)


async def build() -> dict[str, Any]:
    """Return ``{"facts": {...}, "components": [...]}`` from the registry."""
    facts: dict[str, Any] = {}
    components: list[dict[str, Any]] = []
    for collector in collectors():
        try:
            result = await run_collector(collector)
        except Exception as exc:
            log.warning("inventory_collector_failed", collector=collector.name, error=str(exc))
            continue
        if collector.kind == "facts":
            for key, value in dict(result).items():
                if key in facts:
                    log.warning("inventory_fact_collision", collector=collector.name, key=key)
                    continue
                facts[key] = value
        else:
            components.extend(result)
    return {"facts": facts, "components": components}
