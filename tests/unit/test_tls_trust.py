"""Outbound TLS verifies against the host's CA store, not certifi's.

The bug these cover is not hypothetical and has now arrived by three separate
routes: a server behind a private CA is trusted by the machine the agent runs
on, and rejected by certifi, so enrolment fails on a host where `curl` to the
same URL succeeds.

The important test here does a real handshake against a real server using a
private CA, because that is the thing that was broken. Asserting on which file
paths get probed would have passed happily while the agent still could not
connect.
"""

from __future__ import annotations

import ssl
import subprocess
from pathlib import Path

import pytest

from sum_agent.core import tls


@pytest.fixture(scope="module")
def private_ca(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """A throwaway CA and a localhost server certificate it signed.

    Stands in for an organisation's internal CA: present in the host's store on
    a real deployment, and never in certifi.
    """
    d = tmp_path_factory.mktemp("ca")
    ca_key, ca_crt = d / "ca.key", d / "ca.crt"
    srv_key, srv_csr, srv_crt = d / "srv.key", d / "srv.csr", d / "srv.crt"
    ext = d / "srv.ext"
    ext.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n")

    def run(*args: str) -> None:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr

    openssl = "/usr/bin/openssl"
    run(
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=OpenSUM Test CA",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca_crt),
    )
    run(
        openssl,
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=localhost",
        "-keyout",
        str(srv_key),
        "-out",
        str(srv_csr),
    )
    run(
        openssl,
        "x509",
        "-req",
        "-in",
        str(srv_csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-days",
        "1",
        "-extfile",
        str(ext),
        "-out",
        str(srv_crt),
    )
    return ca_crt, srv_crt, srv_key


def _serve_tls(crt: Path, key: Path) -> tuple[str, int, object]:
    """A one-shot HTTPS server on localhost. Returns (host, port, server)."""
    import http.server
    import threading

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(crt), keyfile=str(key))

    class Quiet(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_a: object) -> None:
            return

    srv = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "127.0.0.1", srv.server_port, srv


def test_certifi_alone_cannot_reach_a_private_ca_server(
    private_ca: tuple[Path, Path, Path],
) -> None:
    """The failure being fixed, reproduced. httpx's default trusts certifi."""
    import certifi
    import httpx

    _ca, crt, key = private_ca
    host, port, srv = _serve_tls(crt, key)
    try:
        certifi_ctx = ssl.create_default_context(cafile=certifi.where())
        with httpx.Client(verify=certifi_ctx) as c, pytest.raises(httpx.ConnectError):
            c.get(f"https://{host}:{port}/")
    finally:
        srv.shutdown()  # type: ignore[attr-defined]


def test_system_trust_context_reaches_a_private_ca_server(
    private_ca: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fix. With the CA in the host's store, the same request succeeds.

    ``SSL_CERT_FILE`` stands in for the store here because a test cannot write
    to /etc; `create_default_context` honours it exactly as it honours the
    system paths, which is the mechanism being relied on.
    """
    import httpx

    ca, crt, key = private_ca
    host, port, srv = _serve_tls(crt, key)
    try:
        monkeypatch.setenv("SSL_CERT_FILE", str(ca))
        with httpx.Client(verify=tls.system_trust_context()) as c:
            resp = c.get(f"https://{host}:{port}/")
        assert resp.status_code == 200
    finally:
        srv.shutdown()  # type: ignore[attr-defined]


def test_the_agent_client_itself_uses_the_system_store(
    private_ca: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the agent's own client builder, which is what enrol
    and every other call actually go through."""
    import anyio

    from sum_agent.core import http as agent_http
    from sum_agent.settings import Settings

    ca, crt, key = private_ca
    host, port, srv = _serve_tls(crt, key)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))

    async def _go() -> int:
        settings = Settings(server_url=f"https://{host}:{port}")
        async with agent_http.unauth_client(
            base_url=f"https://{host}:{port}", settings=settings
        ) as client:
            resp = await client.get("/")
            return resp.status_code

    try:
        assert anyio.run(_go) == 200
    finally:
        srv.shutdown()  # type: ignore[attr-defined]


def test_probes_a_bundle_that_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A frozen binary cannot rely on OpenSSL's compiled-in paths, which come
    from the CI runner that built it, so the known locations are probed."""
    ca = tmp_path / "bundle.crt"
    ca.write_text("")
    monkeypatch.setattr(tls, "SYSTEM_CA_FILES", (str(tmp_path / "missing.crt"), str(ca)))
    monkeypatch.setattr(tls, "SYSTEM_CA_DIRS", ())
    loaded: list[str] = []
    real = ssl.SSLContext.load_verify_locations

    def _spy(self: ssl.SSLContext, cafile: str | None = None, **kw: object) -> None:
        if cafile:
            loaded.append(cafile)
        return real(self, cafile=cafile, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", _spy)
    tls.system_trust_context()
    assert loaded == [str(ca)]


def test_missing_store_is_a_warning_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """`create_default_context` may still have found certificates by other
    means, so an unrecognised layout must not take the agent down."""
    monkeypatch.setattr(tls, "SYSTEM_CA_FILES", ("/nonexistent/ca.crt",))
    monkeypatch.setattr(tls, "SYSTEM_CA_DIRS", ("/nonexistent/certs",))
    ctx = tls.system_trust_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_verification_stays_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing here may weaken verification; `tls_insecure` is the only way off
    and it is gated to localhost in settings."""
    ctx = tls.system_trust_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
