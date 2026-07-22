"""Plugin subprocess runtime: line-delimited JSON-RPC 2.0 over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from typing import Any

import structlog

from sum_agent.jobs.registry import JobOutcome
from sum_agent.plugins.cache import PluginEntry

log = structlog.get_logger(__name__)

GRACE_SECONDS_AFTER_TERM = 5


def _frame(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


async def _read_loop(
    stdout: asyncio.StreamReader,
    response_fut: asyncio.Future[dict[str, Any]],
    *,
    plugin_name: str,
) -> None:
    """Reader: route ``id`` messages to the response future; log plugin -> agent calls."""
    while True:
        raw = await stdout.readline()
        if not raw:
            if not response_fut.done():
                response_fut.set_exception(RuntimeError("plugin closed stdout"))
            return
        try:
            msg = json.loads(raw.decode(errors="replace"))
        except json.JSONDecodeError:
            log.warning(
                "plugin_invalid_jsonrpc_line",
                plugin=plugin_name,
                line=raw[:200].decode(errors="replace"),
            )
            continue
        if "id" in msg and ("result" in msg or "error" in msg):
            if not response_fut.done():
                response_fut.set_result(msg)
            continue
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "log":
            log.info(
                "plugin_log",
                plugin=plugin_name,
                level=params.get("level", "info"),
                message=params.get("message", ""),
            )
        elif method == "progress":
            log.info(
                "plugin_progress",
                plugin=plugin_name,
                percent=params.get("percent"),
                note=params.get("note"),
            )
        else:
            log.debug("plugin_unhandled_message", plugin=plugin_name, method=method)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=GRACE_SECONDS_AFTER_TERM)
        return
    except TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await proc.wait()


async def run(
    entry: PluginEntry,
    *,
    capability: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> JobOutcome:
    """Spawn the plugin, exchange one JSON-RPC call, return a ``JobOutcome``."""
    try:
        proc = await asyncio.create_subprocess_exec(
            str(entry.entrypoint),
            cwd=str(entry.plugin_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=True,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (OSError, FileNotFoundError) as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "plugin_spawn_failed", "message": str(exc)},
        }

    assert proc.stdin is not None
    assert proc.stdout is not None

    loop = asyncio.get_running_loop()
    response_fut: asyncio.Future[dict[str, Any]] = loop.create_future()
    reader_task = asyncio.create_task(_read_loop(proc.stdout, response_fut, plugin_name=entry.name))

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "capability.execute",
        "params": {"capability": capability, "payload": payload},
    }
    try:
        proc.stdin.write(_frame(request))
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError) as exc:
        reader_task.cancel()
        await _terminate(proc)
        return {
            "status": "failed",
            "exit_code": proc.returncode,
            "output": {"error": "plugin_write_failed", "message": str(exc)},
        }

    try:
        response = await asyncio.wait_for(response_fut, timeout=timeout_seconds)
    except TimeoutError:
        reader_task.cancel()
        await _terminate(proc)
        return {
            "status": "failed",
            "exit_code": None,
            "output": {"error": "timeout", "timeout_seconds": timeout_seconds},
        }
    finally:
        if not reader_task.done():
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task

    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=GRACE_SECONDS_AFTER_TERM)
    if proc.returncode is None:
        await _terminate(proc)

    if "error" in response:
        err = response["error"]
        return {
            "status": "failed",
            "exit_code": proc.returncode,
            "output": {
                "error": "plugin_returned_error",
                "code": err.get("code"),
                "message": err.get("message"),
                "data": err.get("data"),
            },
        }

    result = response.get("result", {})
    status = result.get("status", "completed")
    if status not in ("completed", "failed"):
        status = "failed"
    return {
        "status": status,
        "exit_code": result.get("exit_code", proc.returncode),
        "output": result.get("output", {}),
    }
