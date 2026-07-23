from __future__ import annotations

from nacl.signing import SigningKey

from sum_agent.core.canonical import canonical_bytes
from sum_agent.core.verify import verify_ed25519


def test_verify_ed25519_round_trip() -> None:
    sk = SigningKey.generate()
    msg = b"hello world"
    sig = sk.sign(msg).signature
    assert verify_ed25519(bytes(sk.verify_key), msg, sig)
    assert not verify_ed25519(bytes(sk.verify_key), msg + b"!", sig)


def test_verify_ed25519_rejects_bad_key_or_sig_length() -> None:
    sk = SigningKey.generate()
    sig = sk.sign(b"m").signature
    assert not verify_ed25519(b"short", b"m", sig)
    assert not verify_ed25519(bytes(sk.verify_key), b"m", b"short")


def test_canonical_bytes_pin() -> None:
    """Pin the canonical format against sum_server's signing helper.

    Sorted keys, no whitespace, ASCII only. If this drifts from the server,
    future signature verification breaks at runtime.
    """
    out = canonical_bytes({"b": 1, "a": {"z": True, "y": "é"}, "c": [1, 2]})
    assert out == b'{"a":{"y":"\\u00e9","z":true},"b":1,"c":[1,2]}'
