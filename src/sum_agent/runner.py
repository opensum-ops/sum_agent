"""Main async loop for the agent daemon."""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from sum_agent import client
from sum_agent.core.errors import ServerError, TransportError
from sum_agent.core.state import State
from sum_agent.inventory.snapshot import build as build_inventory
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)


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


async def run(state: State, settings: Settings) -> None:
    """Top-level daemon entrypoint. Returns when SIGINT/SIGTERM is received."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    inv_task = asyncio.create_task(_inventory_loop(state, settings=settings, stop=stop))
    log.info(
        "agent_started",
        server_url=state.server_url,
        host_id=str(state.host_id),
    )
    try:
        await stop.wait()
    finally:
        inv_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await inv_task
        log.info("agent_stopped")
