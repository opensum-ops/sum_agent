"""Collector framework: a registry the snapshot orchestrator iterates.

Adding an inventory module is two steps:

1. Write a module with a no-arg ``collect()`` (sync or async) returning either
   a ``dict`` of facts (kind ``"facts"``) or a ``list`` of component dicts
   (kind ``"components"``), and call :func:`register` at import time.
2. Import the module in ``inventory/__init__.py`` so registration runs.

Per-collector failures are isolated by the orchestrator: a broken collector
logs a warning and contributes nothing.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

CollectorKind = Literal["facts", "components"]
# Sync or async; returns dict (facts) or list[dict] (components).
CollectFn = Callable[[], Any]


@dataclass(frozen=True)
class Collector:
    name: str
    kind: CollectorKind
    collect: CollectFn


_REGISTRY: list[Collector] = []


def register(name: str, kind: CollectorKind, collect: CollectFn) -> None:
    if any(c.name == name for c in _REGISTRY):
        raise ValueError(f"collector {name!r} already registered")
    _REGISTRY.append(Collector(name=name, kind=kind, collect=collect))


def collectors() -> tuple[Collector, ...]:
    return tuple(_REGISTRY)


async def run_collector(collector: Collector) -> Any:
    """Invoke sync or async uniformly."""
    result = collector.collect()
    if inspect.isawaitable(result):
        return await result
    return result
