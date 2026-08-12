"""Main async loop for the agent daemon: inventory + heartbeat + goodbye."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import signal
from typing import Any

import structlog

from sum_agent import __version__, client, uninstaller, updater
from sum_agent.core.errors import ServerError, TransportError, UpdateError
from sum_agent.core.shutdown import classify_shutdown
from sum_agent.core.state import State
from sum_agent.inventory.facts_system import read_boot_id
from sum_agent.inventory.snapshot import build as build_inventory
from sum_agent.settings import Settings

log = structlog.get_logger(__name__)

GOODBYE_TIMEOUT_SECONDS = 5


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


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


async def _heartbeat_loop(
    state: State, *, settings: Settings, stop: asyncio.Event, removed: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            resp = await client.heartbeat(state, settings=settings, boot_id=read_boot_id())
            # A successful heartbeat confirms a freshly-applied update.
            if state.pending_verify is not None:
                updater.confirm(state, settings=settings)
            removal = resp.get("agent_remove") if isinstance(resp, dict) else None
            if (
                removal
                and settings.self_uninstall_enabled
                and await _maybe_self_uninstall(state, removal, settings=settings)
            ):
                # Cleanup is running and will stop this service out from under
                # us. `removed` suppresses the ordinary goodbye: we have already
                # reported, and following it with "stopping" would contradict
                # the report the server is waiting on.
                removed.set()
                stop.set()
                return
            directive = resp.get("agent_update") if isinstance(resp, dict) else None
            if directive and settings.self_update_enabled and state.pending_verify is None:
                await _maybe_self_update(state, directive, settings=settings)
        except (ServerError, TransportError) as exc:
            log.warning("heartbeat_failed", error=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.heartbeat_interval_seconds)
        except TimeoutError:
            continue


async def _maybe_self_uninstall(
    state: State, directive: dict[str, Any], *, settings: Settings
) -> bool:
    """Verify a removal directive, report, then hand off to a detached cleanup.

    Order matters and is the whole subtlety here. The goodbye goes **first**:
    once the cleanup starts it stops this service, and a report that never left
    is the difference between the server knowing the host is clean and waiting
    on it forever. The goodbye is best-effort, so a failure to send is logged
    and removal proceeds anyway; the operator asked for the agent gone, and
    leaving it installed because a report failed would be the wrong trade.

    Returns True when cleanup is running and the daemon should stop.
    """
    if not uninstaller.verify_directive(state, directive):
        log.warning("uninstall_directive_invalid")
        return False
    # Verified before reporting, so an unverifiable directive cannot even
    # provoke a goodbye that would make the server clear this host's data.
    try:
        await asyncio.wait_for(
            client.heartbeat(
                state, settings=settings, running=False, detail="agent_removed", boot_id=None
            ),
            timeout=GOODBYE_TIMEOUT_SECONDS,
        )
        log.info("uninstall_reported")
    except (ServerError, TransportError, TimeoutError) as exc:
        log.warning("uninstall_report_failed", error=str(exc))
    if not uninstaller.apply(state, directive, settings=settings):
        return False
    log.info("uninstall_handed_off")
    return True


async def _maybe_self_update(
    state: State, directive: dict[str, object], *, settings: Settings
) -> None:
    """Apply an update directive if it targets a different version. On success
    this re-execs and does not return; on failure it logs and stays put.
    """
    if directive.get("target_version") == __version__:
        return
    try:
        await updater.apply(state, directive, settings=settings)
    except UpdateError as exc:
        log.warning("self_update_failed", error=str(exc))


async def _pending_verify_watchdog(
    state: State, *, settings: Settings, stop: asyncio.Event
) -> None:
    """If a just-applied update never gets confirmed by a heartbeat, revert."""
    pending = state.pending_verify
    if pending is None:
        return
    timeout = max(1.0, (pending.deadline - _utcnow()).total_seconds())
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=timeout)
    if not stop.is_set() and state.pending_verify is not None:
        log.warning("self_update_verify_timeout", target=pending.target_version)
        updater.revert(state, settings=settings)  # re-execs into the old binary


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
    removed = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    tasks = [
        asyncio.create_task(_inventory_loop(state, settings=settings, stop=stop)),
        asyncio.create_task(_heartbeat_loop(state, settings=settings, stop=stop, removed=removed)),
    ]
    if state.pending_verify is not None:
        # This process is a freshly-applied binary awaiting confirmation.
        log.info("self_update_verifying", target=state.pending_verify.target_version)
        tasks.append(
            asyncio.create_task(_pending_verify_watchdog(state, settings=settings, stop=stop))
        )
    log.info(
        "agent_started",
        server_url=state.server_url,
        host_id=str(state.host_id),
        version=__version__,
    )
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        if not removed.is_set():
            await _send_goodbye(state, settings=settings)
        log.info("agent_stopped", removed=removed.is_set())
