"""TLS trust for outbound connections: always the host's own CA store.

httpx verifies against **certifi** by default, a bundle of public roots vendored
into the Python package. That is the wrong store for this agent. A server behind
an organisation's private CA is trusted by the machine the agent runs on and not
by certifi, so verification fails on a host where `curl` to the same URL
succeeds. It has bitten this project three times now, each by a different route
(2026-07-22 on the first deployment, 2026-08-09 through the installer, and again
on a real enrol), which is why the fix belongs here rather than in another shell
script that exports ``SSL_CERT_FILE``.

The agent talks to exactly one server, chosen by the operator and usually
theirs. The host's trust decisions are the right ones to inherit.
"""

from __future__ import annotations

import contextlib
import os
import ssl

import structlog

log = structlog.get_logger(__name__)

# Bundle files, most specific first. Debian/Ubuntu/Alpine, RHEL family,
# openSUSE, older RHEL, and the BSD-style path some images use.
SYSTEM_CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/pki/tls/cacert.pem",
    "/etc/ssl/cert.pem",
)

# Hashed certificate directories, for distributions that ship those instead of
# (or as well as) a concatenated bundle.
SYSTEM_CA_DIRS = (
    "/etc/ssl/certs",
    "/etc/pki/tls/certs",
)


def system_trust_context() -> ssl.SSLContext:
    """An SSL context verifying against this host's CA store.

    ``create_default_context`` already calls ``load_default_certs``, which
    honours ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` and OpenSSL's compiled-in
    paths. That is not enough on its own for us: in a PyInstaller binary those
    compiled-in paths come from the machine that *built* the binary, which is a
    CI runner, not the host it ends up on. So the known locations are probed
    explicitly as well.

    Loading is additive, so an operator who sets ``SSL_CERT_FILE`` to point at
    an extra bundle keeps that trust in addition to the system's, and nothing
    here can narrow what the host already trusts.
    """
    ctx = ssl.create_default_context()

    loaded: list[str] = []
    for path in SYSTEM_CA_FILES:
        if os.path.isfile(path):
            with contextlib.suppress(OSError, ssl.SSLError):
                ctx.load_verify_locations(cafile=path)
                loaded.append(path)
            break
    for path in SYSTEM_CA_DIRS:
        if os.path.isdir(path):
            with contextlib.suppress(OSError, ssl.SSLError):
                ctx.load_verify_locations(capath=path)
                loaded.append(path)
            break

    if not loaded:
        # Not fatal: create_default_context may still have found certificates
        # through OpenSSL's own defaults. Worth saying out loud, because the
        # symptom otherwise is a verification failure with no explanation.
        log.warning("system_ca_store_not_found", probed=list(SYSTEM_CA_FILES))
    return ctx
