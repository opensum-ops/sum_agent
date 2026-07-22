"""Plugin manifest schema + signature/integrity verification."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sum_agent.core.canonical import canonical_bytes
from sum_agent.core.errors import PluginError
from sum_agent.core.verify import verify_ed25519


class SupportedTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    os: str
    arch: str


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    supported: list[SupportedTarget]
    signing_key_fingerprint: str
    capabilities: list[str] = Field(min_length=1)
    required_privileges: list[str] = Field(default_factory=list)
    entrypoint: str
    binary_sha256: str
    signature_b64: str

    def unsigned_payload(self) -> dict[str, Any]:
        d = self.model_dump()
        d.pop("signature_b64", None)
        return d


def fingerprint(pubkey_bytes: bytes) -> str:
    return base64.b64encode(hashlib.sha256(pubkey_bytes).digest()).decode()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(
    manifest: PluginManifest,
    *,
    plugin_dir: Path,
    trusted_pubkeys_b64: list[str],
) -> None:
    """Verify the manifest signature, key trust, and on-disk binary hash."""
    matching: list[bytes] = []
    for k_b64 in trusted_pubkeys_b64:
        try:
            k_bytes = base64.b64decode(k_b64)
        except (ValueError, binascii.Error):
            continue
        if fingerprint(k_bytes) == manifest.signing_key_fingerprint:
            matching.append(k_bytes)
    if not matching:
        raise PluginError(
            f"plugin {manifest.name}: no trusted key matches fingerprint "
            f"{manifest.signing_key_fingerprint}"
        )

    sig = base64.b64decode(manifest.signature_b64)
    message = canonical_bytes(manifest.unsigned_payload())
    if not any(verify_ed25519(k, message, sig) for k in matching):
        raise PluginError(f"plugin {manifest.name}: signature did not verify")

    bin_path = (plugin_dir / manifest.entrypoint).resolve()
    if not bin_path.is_file():
        raise PluginError(f"plugin {manifest.name}: entrypoint not found at {bin_path}")
    try:
        bin_path.relative_to(plugin_dir.resolve())
    except ValueError as exc:
        raise PluginError(f"plugin {manifest.name}: entrypoint escapes plugin dir") from exc

    actual = sha256_file(bin_path)
    if actual.lower() != manifest.binary_sha256.lower():
        raise PluginError(
            f"plugin {manifest.name}: binary sha256 mismatch "
            f"(expected {manifest.binary_sha256}, got {actual})"
        )
