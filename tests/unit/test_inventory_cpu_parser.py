from __future__ import annotations

from sum_agent.inventory import cpu

CPUINFO_DUAL_SOCKET = """\
processor	: 0
vendor_id	: GenuineIntel
cpu family	: 6
model name	: Intel(R) Xeon(R) Gold 6242
physical id	: 0
cpu cores	: 16
cpu MHz		: 2800.000

processor	: 1
vendor_id	: GenuineIntel
model name	: Intel(R) Xeon(R) Gold 6242
physical id	: 0
cpu cores	: 16
cpu MHz		: 2800.000

processor	: 32
vendor_id	: GenuineIntel
model name	: Intel(R) Xeon(R) Gold 6242
physical id	: 1
cpu cores	: 16
cpu MHz		: 2800.000

"""


def test_parses_two_sockets() -> None:
    out = cpu.collect(cpuinfo=CPUINFO_DUAL_SOCKET)
    assert len(out) == 2
    assert out[0]["slot"] == "cpu0"
    assert out[0]["attrs"]["cores"] == 16
    assert out[0]["attrs"]["threads"] == 2
    assert out[0]["attrs"]["base_hz"] == 2_800_000_000
    assert out[1]["slot"] == "cpu1"
    assert out[1]["attrs"]["threads"] == 1


def test_empty_cpuinfo_uses_psutil_fallback() -> None:
    out = cpu.collect(cpuinfo="")
    assert len(out) == 1
    assert out[0]["kind"] == "cpu"
    assert out[0]["attrs"]["cores"] >= 1
