"""Collector framework: registration, snapshot assembly, error isolation."""

from __future__ import annotations

from typing import Any

import pytest

from sum_agent.inventory import base
from sum_agent.inventory.snapshot import build


def test_all_builtin_collectors_registered() -> None:
    import sum_agent.inventory  # noqa: F401  triggers registration

    names = {c.name for c in base.collectors()}
    assert {
        "cpu",
        "memory",
        "disks",
        "nics",
        "gpu",
        "facts_system",
        "facts_os",
        "facts_network",
        "facts_agent",
    } <= names


def test_duplicate_registration_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):
        base.register("cpu", "components", lambda: [])


async def test_snapshot_shape_and_error_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    def good_facts() -> dict[str, Any]:
        return {"alpha": 1}

    async def good_async_facts() -> dict[str, Any]:
        return {"beta": "two"}

    def boom() -> dict[str, Any]:
        raise RuntimeError("collector exploded")

    def comps() -> list[dict[str, Any]]:
        return [{"kind": "disk"}]

    fake = (
        base.Collector("f1", "facts", good_facts),
        base.Collector("f2", "facts", good_async_facts),
        base.Collector("bad", "facts", boom),
        base.Collector("c1", "components", comps),
    )
    monkeypatch.setattr(base, "_REGISTRY", list(fake))

    snapshot = await build()
    assert snapshot["facts"] == {"alpha": 1, "beta": "two"}
    assert snapshot["components"] == [{"kind": "disk"}]


async def test_snapshot_fact_collision_keeps_first(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = (
        base.Collector("f1", "facts", lambda: {"k": "first"}),
        base.Collector("f2", "facts", lambda: {"k": "second"}),
    )
    monkeypatch.setattr(base, "_REGISTRY", list(fake))
    snapshot = await build()
    assert snapshot["facts"] == {"k": "first"}


async def test_live_snapshot_has_core_facts() -> None:
    """The real registry produces the identity facts on any Linux host."""
    import sum_agent.inventory  # noqa: F401

    snapshot = await build()
    for key in ("hostname", "kernel", "arch", "boot_time", "agent_version"):
        assert key in snapshot["facts"], key
    assert isinstance(snapshot["components"], list)
