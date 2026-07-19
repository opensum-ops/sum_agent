"""Orchestrator: build a full inventory snapshot across collectors.

Per-collector failures are caught, logged, and ignored: inventory is
best-effort and partial snapshots are preferable to none.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from sum_agent.inventory import cpu, disks, gpu, memory, nics

log = structlog.get_logger(__name__)


async def _safe_async(
    name: str, fn: Callable[[], Awaitable[list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    try:
        return await fn()
    except Exception as exc:
        log.warning("inventory_collector_failed", collector=name, error=str(exc))
        return []


def _safe_sync(name: str, fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        return fn()
    except Exception as exc:
        log.warning("inventory_collector_failed", collector=name, error=str(exc))
        return []


async def build() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items += _safe_sync("cpu", cpu.collect)
    items += _safe_sync("memory", memory.collect)
    items += await _safe_async("disks", disks.collect)
    items += _safe_sync("nics", nics.collect)
    items += await _safe_async("gpu", gpu.collect)
    return items
