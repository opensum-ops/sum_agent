"""Dispatch a server-signed job to its capability handler."""

from __future__ import annotations

import asyncio
import traceback
from typing import Any

import structlog

from sum_agent.core.errors import SignatureError
from sum_agent.jobs import verify
from sum_agent.jobs.registry import JobOutcome, registry

log = structlog.get_logger(__name__)


def _failed(reason: str, **extra: Any) -> JobOutcome:
    return {
        "status": "failed",
        "exit_code": None,
        "output": {"error": reason, **extra},
    }


async def execute(
    job: dict[str, Any],
    *,
    server_public_key_b64: str,
    timeout_seconds: int,
) -> JobOutcome:
    """Verify and run a server job under a timeout. Always returns a JobOutcome."""
    try:
        verify.verify(job, server_public_key_b64=server_public_key_b64)
    except SignatureError as exc:
        log.warning("job_signature_invalid", job_id=str(job.get("id")), error=str(exc))
        return _failed("signature_invalid")

    capability = job["capability"]
    handler = registry().get(capability)
    if handler is None:
        log.warning(
            "job_unknown_capability",
            job_id=str(job.get("id")),
            capability=capability,
        )
        return _failed("unknown_capability", capability=capability)

    try:
        return await asyncio.wait_for(handler(job["payload"]), timeout=timeout_seconds)
    except TimeoutError:
        log.warning("job_timeout", job_id=str(job.get("id")), capability=capability)
        return _failed("timeout", timeout_seconds=timeout_seconds)
    except Exception as exc:
        log.exception("job_handler_raised", job_id=str(job.get("id")))
        return _failed(
            "handler_error",
            exception=exc.__class__.__name__,
            message=str(exc),
            traceback=traceback.format_exc(),
        )
