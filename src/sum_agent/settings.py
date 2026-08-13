"""Agent settings (pydantic-settings).

All keys load from env with prefix ``SUM_AGENT_``. The `inventory` and `version`
CLI subcommands don't require ``SERVER_URL`` so it's optional here; the `run`
and `enroll` subcommands enforce presence at use time.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogFormat(StrEnum):
    console = "console"
    json = "json"


def _expand(p: str) -> Path:
    return Path(p).expanduser()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUM_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server_url: str = ""
    state_dir: Path = Field(default=Path("~/.local/state/sum-agent"))

    inventory_interval_seconds: int = Field(default=3600, ge=10)
    heartbeat_interval_seconds: int = Field(default=30, ge=5)

    # Self-update: apply server-signed update directives (frozen binary only).
    self_update_enabled: bool = True
    # How long a freshly-applied binary has to establish itself before the
    # agent reverts to the previous binary.
    self_update_verify_seconds: int = Field(default=120, ge=15)

    # Self-uninstall: apply server-signed removal directives (frozen binary
    # only). Off switch for an operator who would rather remove agents by hand.
    self_uninstall_enabled: bool = True
    # What the installer put where. Defaults match sum_server's install/service
    # constants; the two are one contract about the layout on a host, and the
    # uninstaller has to name the same paths to undo it.
    service_name: str = "sum-agent"
    unit_path: str = "/etc/systemd/system/sum-agent.service"
    env_file: str = "/etc/sum-agent/agent.env"

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: LogFormat = LogFormat.console

    tls_insecure: bool = False

    @field_validator("state_dir", mode="before")
    @classmethod
    def _expand_path(cls, v: str | Path) -> Path | str:
        if v == "":
            return v
        return _expand(str(v))

    @model_validator(mode="after")
    def _defaults_and_safety(self) -> Settings:
        if self.tls_insecure and self.server_url:
            host = urlparse(self.server_url).hostname or ""
            if host not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError(
                    "tls_insecure=true is only allowed when server_url points at localhost"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def require_server_url(s: Settings) -> str:
    if not s.server_url:
        raise RuntimeError("SUM_AGENT_SERVER_URL is required for this command")
    return s.server_url
