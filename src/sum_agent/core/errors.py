"""Agent error hierarchy."""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base for all sum_agent errors."""


class TransportError(AgentError):
    """Network / TLS / connection problem reaching the server."""


class ServerError(AgentError):
    """The server returned a structured error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{http_status} {code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


class NotEnrolledError(AgentError):
    """No persisted state was found; the user must run ``sum-agent enroll`` first."""


class StateCorruptedError(AgentError):
    """Persisted state file failed schema validation."""


class SignatureError(AgentError):
    """A signature did not verify against the registered server public key."""


class UpdateError(AgentError):
    """A self-update could not be staged or applied (verify/download/smoke)."""
