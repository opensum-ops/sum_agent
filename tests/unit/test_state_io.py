from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest

from sum_agent.core import state as state_mod
from sum_agent.core.errors import NotEnrolledError, StateCorruptedError


def _sample(server_url: str = "https://example.com") -> state_mod.State:
    return state_mod.State(
        server_url=server_url,
        host_id=uuid.uuid4(),
        agent_token="t" * 64,
        signing_public_key_b64="A" * 44,
        enrolled_at=dt.datetime.now(tz=dt.UTC),
    )


def test_save_and_load_round_trip(state_dir: Path) -> None:
    s = _sample()
    path = state_mod.save(state_dir, s)
    assert path.exists()
    loaded = state_mod.load(state_dir)
    assert loaded.server_url == s.server_url
    assert loaded.agent_token == s.agent_token


def test_state_file_is_mode_0600(state_dir: Path) -> None:
    s = _sample()
    path = state_mod.save(state_dir, s)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600


def test_load_missing_raises_not_enrolled(state_dir: Path) -> None:
    with pytest.raises(NotEnrolledError):
        state_mod.load(state_dir)


def test_load_corrupted_raises(state_dir: Path) -> None:
    (state_dir / state_mod.STATE_FILENAME).write_text("not json")
    with pytest.raises(StateCorruptedError):
        state_mod.load(state_dir)
