"""Main async loop for the agent daemon."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

import structlog

from sum_agent import client
from sum_agent.core.errors import ServerError, TransportError
from sum_agent.core.state import State
from sum_agent.inventory.snapshot import build as build_inventory
from sum_agent.jobs import builtins  # noqa: F401  registers built-in handlers
from sum_agent.jobs.dispatch import execute as dispatch_execute
from sum_agent.jobs.registry import registry
from sum_agent.plugins.cache import PluginEntry
from sum_agent.plugins.cache import discover as discover_plugins
from sum_agent.plugins.runtime import run as run_plugin
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)


async def _safe_report(
    state: State,
    job_id: str,
    outcome: dict[str, Any],
    *,
    settings: Settings,
) -> None:
    try:
        await client.report_result(state, job_id, outcome=outcome, settings=settings)
    except (ServerError, TransportError) as exc:
        log.warning("report_result_failed", job_id=job_id, error=str(exc))


def _bind_plugin_handler(capability: str, entry: PluginEntry, *, settings: Settings) -> None:
    """Register a transient handler that dispatches to the plugin subprocess."""
    if registry().get(capability) is not None:
        return

    async def _plugin_handler(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_plugin(
            entry,
            capability=capability,
            payload=payload,
            timeout_seconds=settings.job_timeout_seconds,
        )

    registry().register(capability, _plugin_handler)


async def _handle_job(state: State, job: dict[str, Any], *, settings: Settings) -> None:
    job_id = str(job["id"])
    capability = job["capability"]
    log.info("job_received", job_id=job_id, capability=capability)

    try:
        await client.pickup(state, job_id, settings=settings)
    except ServerError as exc:
        log.warning("pickup_failed", job_id=job_id, error=str(exc))
        return
    except TransportError as exc:
        log.warning("pickup_transport_error", job_id=job_id, error=str(exc))
        return

    outcome = await dispatch_execute(
        job,
        server_public_key_b64=state.signing_public_key_b64,
        timeout_seconds=settings.job_timeout_seconds,
    )
    log.info(
        "job_finished",
        job_id=job_id,
        capability=capability,
        status=outcome["status"],
    )
    await _safe_report(state, job_id, outcome, settings=settings)


async def _inventory_loop(state: State, *, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            components = await build_inventory()
            await client.submit_inventory(state, components, settings=settings)
            log.info("inventory_submitted", count=len(components))
        except (ServerError, TransportError) as exc:
            log.warning("inventory_submit_failed", error=str(exc))
        except Exception:
            log.exception("inventory_loop_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.inventory_interval_seconds)
        except TimeoutError:
            continue


async def _poll_loop(state: State, *, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        jobs: list[dict[str, Any]] = []
        try:
            jobs = await client.poll_jobs(state, settings=settings)
        except (ServerError, TransportError) as exc:
            log.warning("poll_failed", error=str(exc))
        for job in jobs:
            if stop.is_set():
                break
            await _handle_job(state, job, settings=settings)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval_seconds)
        except TimeoutError:
            continue


async def run(state: State, settings: Settings) -> None:
    """Top-level daemon entrypoint. Returns when SIGINT/SIGTERM is received."""
    plugins_dir = settings.plugins_dir or settings.state_dir / "plugins"
    plugin_index = discover_plugins(
        plugins_dir,
        trusted_pubkeys_b64=settings.trusted_plugin_key_list(),
    )
    for cap, entry in plugin_index.items():
        _bind_plugin_handler(cap, entry, settings=settings)
    if plugin_index:
        log.info(
            "plugins_loaded",
            count=len(plugin_index),
            capabilities=sorted(plugin_index),
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    inv_task = asyncio.create_task(_inventory_loop(state, settings=settings, stop=stop))
    poll_task = asyncio.create_task(_poll_loop(state, settings=settings, stop=stop))
    log.info(
        "agent_started",
        server_url=state.server_url,
        server_id=str(state.server_id),
    )
    try:
        await stop.wait()
    finally:
        for t in (inv_task, poll_task):
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.gather(inv_task, poll_task, return_exceptions=True)
        log.info("agent_stopped")
