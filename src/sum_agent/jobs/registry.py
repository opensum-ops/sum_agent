"""Capability registry. Built-ins register themselves at import time."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

JobOutcome = dict[str, Any]
"""``{"status": "completed"|"failed", "exit_code": int|None, "output": dict}``."""

Handler = Callable[[dict[str, Any]], Awaitable[JobOutcome]]


@dataclass
class Registry:
    _handlers: dict[str, Handler] = field(default_factory=dict)

    def register(self, capability: str, handler: Handler) -> None:
        self._handlers[capability] = handler

    def get(self, capability: str) -> Handler | None:
        return self._handlers.get(capability)

    def names(self) -> list[str]:
        return sorted(self._handlers)


_REGISTRY = Registry()


def registry() -> Registry:
    return _REGISTRY


def register_builtin(capability: str) -> Callable[[Handler], Handler]:
    """Decorator: bind a built-in capability handler into the registry."""

    def _decorator(fn: Handler) -> Handler:
        _REGISTRY.register(capability, fn)
        return fn

    return _decorator
