"""Test harness. No network — agent tests are unit-scoped."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _agent_env(tmp_path_factory: pytest.TempPathFactory) -> Path:
    state_dir = tmp_path_factory.mktemp("sum-agent-state")
    os.environ.setdefault("SUM_AGENT_STATE_DIR", str(state_dir))
    os.environ.setdefault("SUM_AGENT_LOG_LEVEL", "warning")
    return state_dir


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d
