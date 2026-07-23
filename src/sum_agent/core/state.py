"""Persistent agent state at ``$STATE_DIR/state.json`` with mode 0600.

Atomic writes via tempfile + ``os.replace``. Schema-validated on read.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel, ValidationError

from sum_agent.core.errors import NotEnrolledError, StateCorruptedError

STATE_FILENAME = "state.json"


class State(BaseModel):
    server_url: str
    host_id: uuid.UUID
    agent_token: str
    signing_public_key_b64: str
    enrolled_at: dt.datetime


def _path(state_dir: Path) -> Path:
    return state_dir / STATE_FILENAME


def save(state_dir: Path, state: State) -> Path:
    """Persist ``state`` atomically. Returns the resolved path."""
    state_dir.mkdir(parents=True, exist_ok=True)
    target = _path(state_dir)
    payload = state.model_dump(mode="json")

    fd, tmp_name = tempfile.mkstemp(prefix=".state-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return target


def load(state_dir: Path) -> State:
    target = _path(state_dir)
    if not target.exists():
        raise NotEnrolledError(f"no agent state at {target}; run `sum-agent enroll` first")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return State.model_validate(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateCorruptedError(f"could not read state at {target}: {exc}") from exc
    except ValidationError as exc:
        raise StateCorruptedError(f"state at {target} failed schema validation:\n{exc}") from exc


def exists(state_dir: Path) -> bool:
    return _path(state_dir).exists()
