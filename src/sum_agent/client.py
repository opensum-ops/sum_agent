"""API client wrappers around the http helpers."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sum_agent.core import http
from sum_agent.core.state import State
from sum_agent.settings import Settings


async def enroll(*, server_url: str, enrollment_token: str, settings: Settings) -> State:
    """POST ``/api/v1/agents/enroll``. Returns a fully constructed :class:`State`."""
    async with http.unauth_client(base_url=server_url, settings=settings) as c:
        body = await http.request_json(
            c,
            "POST",
            "/api/v1/agents/enroll",
            json={"enrollment_token": enrollment_token},
        )
    return State(
        server_url=server_url,
        host_id=uuid.UUID(body["host_id"]),
        agent_token=body["agent_token"],
        signing_public_key_b64=body["signing_public_key"],
        enrolled_at=dt.datetime.now(tz=dt.UTC),
    )


async def heartbeat(
    state: State,
    *,
    settings: Settings,
    running: bool = True,
    detail: str | None = None,
    boot_id: str | None = None,
) -> dict[str, Any]:
    """POST ``/api/v1/agents/heartbeat``.

    ``running=False`` sends the goodbye (``state: stopping``) with ``detail``
    explaining why (rebooting, powered_off, agent_stop).
    """
    payload: dict[str, Any] = {"state": "running" if running else "stopping"}
    if detail is not None:
        payload["detail"] = detail
    if boot_id is not None:
        payload["boot_id"] = boot_id
    async with http.authed_client(
        base_url=state.server_url,
        bearer=state.agent_token,
        settings=settings,
    ) as c:
        body: dict[str, Any] = await http.request_json(
            c, "POST", "/api/v1/agents/heartbeat", json=payload
        )
        return body


async def submit_inventory(
    state: State, snapshot: dict[str, Any], *, settings: Settings
) -> dict[str, int]:
    """POST the full snapshot: ``{"facts": {...}, "components": [...]}``."""
    async with http.authed_client(
        base_url=state.server_url,
        bearer=state.agent_token,
        settings=settings,
    ) as c:
        body: dict[str, int] = await http.request_json(
            c,
            "POST",
            "/api/v1/agents/inventory",
            json={
                "facts": snapshot.get("facts", {}),
                "components": snapshot.get("components", []),
            },
        )
        return body
