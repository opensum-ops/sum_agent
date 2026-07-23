"""Main async loop for the agent daemon: inventory + heartbeat + goodbye."""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from sum_agent import client
from sum_agent.core.errors import ServerError, TransportError
from sum_agent.core.shutdown import classify_shutdown
from sum_agent.core.state import State
from sum_agent.inventory.facts_system import read_boot_id
from sum_agent.inventory.snapshot import build as build_inventory
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)

GOODBYE_TIMEOUT_SECONDS = 5


async def _inventory_loop(state: State, *, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            snapshot = await build_inventory()
            await client.submit_inventory(state, snapshot, settings=settings)
            log.info(
                "inventory_submitted",
                facts=len(snapshot["facts"]),
                components=len(snapshot["components"]),
            )
        except (ServerError, TransportError) as exc:
            log.warning("inventory_submit_failed", error=str(exc))
        except Exception:
            log.exception("inventory_loop_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.inventory_interval_seconds)
        except TimeoutError:
            continue


async def _heartbeat_loop(state: State, *, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await client.heartbeat(state, settings=settings, boot_id=read_boot_id())
        except (ServerError, TransportError) as exc:
            log.warning("heartbeat_failed", error=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.heartbeat_interval_seconds)
        except TimeoutError:
            continue


async def _send_goodbye(state: State, *, settings: Settings) -> None:
    """Best-effort goodbye so the server can distinguish a clean stop from a crash."""
    detail = classify_shutdown()
    try:
        await asyncio.wait_for(
            client.heartbeat(
                state,
                settings=settings,
                running=False,
                detail=detail,
                boot_id=read_boot_id(),
            ),
            timeout=GOODBYE_TIMEOUT_SECONDS,
        )
        log.info("goodbye_sent", detail=detail)
    except (ServerError, TransportError, TimeoutError) as exc:
        log.warning("goodbye_failed", detail=detail, error=str(exc))


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

    tasks = [
        asyncio.create_task(_inventory_loop(state, settings=settings, stop=stop)),
        asyncio.create_task(_heartbeat_loop(state, settings=settings, stop=stop)),
    ]
    log.info(
        "agent_started",
        server_url=state.server_url,
        host_id=str(state.host_id),
    )
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        await _send_goodbye(state, settings=settings)
        log.info("agent_stopped")
