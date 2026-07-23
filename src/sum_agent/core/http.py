"""Async HTTP client wrapper.

Wraps ``httpx.AsyncClient`` with bearer-header injection, error-envelope parsing,
and a ``TLS_INSECURE`` escape hatch for dev (gated to localhost in settings).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog

from sum_agent import __version__
from sum_agent.core.errors import ServerError, TransportError
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _build_client(*, base_url: str, bearer: str | None, settings: Settings) -> httpx.AsyncClient:
    headers: dict[str, str] = {"User-Agent": f"sum-agent/{__version__}"}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    verify: bool | str = True
    if settings.tls_insecure:
        verify = False
        log.warning("tls_insecure_enabled", server_url=base_url)
    return httpx.AsyncClient(
        base_url=base_url, headers=headers, verify=verify, timeout=DEFAULT_TIMEOUT
    )


@asynccontextmanager
async def authed_client(
    *, base_url: str, bearer: str, settings: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    client = _build_client(base_url=base_url, bearer=bearer, settings=settings)
    try:
        yield client
    finally:
        await client.aclose()


@asynccontextmanager
async def unauth_client(*, base_url: str, settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    client = _build_client(base_url=base_url, bearer=None, settings=settings)
    try:
        yield client
    finally:
        await client.aclose()


def raise_for_status(resp: httpx.Response) -> None:
    """Convert error responses to ``ServerError`` / ``TransportError``."""
    if 200 <= resp.status_code < 300:
        return
    try:
        body = resp.json()
        env = body.get("error", {}) if isinstance(body, dict) else {}
    except Exception:
        env = {}
    code = env.get("code", "http_error")
    message = env.get("message", resp.text[:200])
    details = env.get("details", {}) if isinstance(env, dict) else {}
    raise ServerError(code, message, http_status=resp.status_code, details=details)


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: Any = None,
) -> Any:
    try:
        resp = await client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        raise TransportError(f"{method} {url}: {exc.__class__.__name__}: {exc}") from exc
    raise_for_status(resp)
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()
