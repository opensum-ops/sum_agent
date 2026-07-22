"""Local plugin cache: scan + verify plugins under ``$PLUGINS_DIR``."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path

import structlog
from pydantic import ValidationError

from sum_agent.plugins.manifest import PluginManifest, verify_manifest

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PluginEntry:
    name: str
    version: str
    plugin_dir: Path
    entrypoint: Path
    capabilities: tuple[str, ...]


def current_target() -> tuple[str, str]:
    sys = platform.system().lower()
    if sys == "linux":
        os_name = "linux"
    elif sys == "darwin":
        os_name = "macos"
    else:
        os_name = sys
    arch = platform.machine().lower()
    if arch == "x86_64":
        arch = "amd64"
    return os_name, arch


def _supports(manifest: PluginManifest, target: tuple[str, str]) -> bool:
    return any((s.os.lower(), s.arch.lower()) == target for s in manifest.supported)


def discover(plugins_dir: Path, *, trusted_pubkeys_b64: list[str]) -> dict[str, PluginEntry]:
    """Discover, verify, and index every plugin under ``plugins_dir``.

    Returns a ``capability -> PluginEntry`` mapping. Failures are logged and the
    plugin is skipped; this function never raises on a bad plugin.
    """
    out: dict[str, PluginEntry] = {}
    if not plugins_dir.exists():
        return out
    target = current_target()
    for plugin_dir in sorted(plugins_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = PluginManifest.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            log.warning(
                "plugin_manifest_invalid",
                plugin_dir=str(plugin_dir),
                error=str(exc),
            )
            continue
        if not _supports(manifest, target):
            log.info(
                "plugin_not_supported_on_host",
                plugin=manifest.name,
                version=manifest.version,
                target=target,
            )
            continue
        try:
            verify_manifest(
                manifest,
                plugin_dir=plugin_dir,
                trusted_pubkeys_b64=trusted_pubkeys_b64,
            )
        except Exception as exc:
            log.warning(
                "plugin_verification_failed",
                plugin=manifest.name,
                error=str(exc),
            )
            continue
        entry = PluginEntry(
            name=manifest.name,
            version=manifest.version,
            plugin_dir=plugin_dir,
            entrypoint=(plugin_dir / manifest.entrypoint).resolve(),
            capabilities=tuple(manifest.capabilities),
        )
        for cap in manifest.capabilities:
            if cap in out:
                log.warning(
                    "plugin_capability_collision",
                    capability=cap,
                    existing=out[cap].name,
                    incoming=entry.name,
                )
                continue
            out[cap] = entry
    return out
