from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from nacl.signing import SigningKey

from sum_agent.core.canonical import canonical_bytes
from sum_agent.core.errors import PluginError
from sum_agent.plugins.manifest import PluginManifest, fingerprint, verify_manifest


def _make_plugin(
    tmp_path: Path,
    *,
    sk: SigningKey,
    name: str = "demo",
    binary: bytes = b"#!/bin/sh\necho hi\n",
) -> tuple[Path, PluginManifest, str]:
    plugin_dir = tmp_path / f"{name}-1.0.0"
    plugin_dir.mkdir()
    bin_path = plugin_dir / "run.sh"
    bin_path.write_bytes(binary)
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    fp = fingerprint(bytes(sk.verify_key))
    sha = hashlib.sha256(binary).hexdigest()

    unsigned = {
        "name": name,
        "version": "1.0.0",
        "supported": [{"os": "linux", "arch": "amd64"}],
        "signing_key_fingerprint": fp,
        "capabilities": [f"plugin.{name}"],
        "required_privileges": [],
        "entrypoint": "run.sh",
        "binary_sha256": sha,
    }
    sig = sk.sign(canonical_bytes(unsigned)).signature
    manifest = PluginManifest.model_validate(
        {**unsigned, "signature_b64": base64.b64encode(sig).decode()}
    )
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest.model_dump(), indent=2))
    return plugin_dir, manifest, pub_b64


def test_verify_happy_path(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    plugin_dir, manifest, pub_b64 = _make_plugin(tmp_path, sk=sk)
    verify_manifest(manifest, plugin_dir=plugin_dir, trusted_pubkeys_b64=[pub_b64])


def test_verify_rejects_untrusted_key(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    other = SigningKey.generate()
    plugin_dir, manifest, _ = _make_plugin(tmp_path, sk=sk)
    other_b64 = base64.b64encode(bytes(other.verify_key)).decode()
    with pytest.raises(PluginError):
        verify_manifest(manifest, plugin_dir=plugin_dir, trusted_pubkeys_b64=[other_b64])


def test_verify_rejects_binary_tamper(tmp_path: Path) -> None:
    sk = SigningKey.generate()
    plugin_dir, manifest, pub_b64 = _make_plugin(tmp_path, sk=sk)
    (plugin_dir / "run.sh").write_bytes(b"#!/bin/sh\necho TAMPERED\n")
    with pytest.raises(PluginError):
        verify_manifest(manifest, plugin_dir=plugin_dir, trusted_pubkeys_b64=[pub_b64])
