from __future__ import annotations

from pathlib import Path

from sum_agent.inventory import nics


def _make_iface(root: Path, name: str, *, mac: str, speed: str = "1000") -> None:
    iface = root / name
    iface.mkdir(parents=True)
    (iface / "address").write_text(mac)
    (iface / "speed").write_text(speed)


def test_picks_physical_ifaces_and_skips_virtual(tmp_path: Path) -> None:
    _make_iface(tmp_path, "eth0", mac="aa:bb:cc:dd:ee:01")
    _make_iface(tmp_path, "ens1", mac="aa:bb:cc:dd:ee:02", speed="10000")
    _make_iface(tmp_path, "docker0", mac="02:42:00:00:00:01")
    _make_iface(tmp_path, "lo", mac="00:00:00:00:00:00")

    out = nics.collect(sys_net=tmp_path)
    slots = sorted(c["slot"] for c in out)
    assert slots == ["ens1", "eth0"]

    eth0 = next(c for c in out if c["slot"] == "eth0")
    assert eth0["attrs"]["mac"] == "aa:bb:cc:dd:ee:01"
    assert eth0["attrs"]["speed_mbps"] == 1000


def test_invalid_mac_is_dropped(tmp_path: Path) -> None:
    _make_iface(tmp_path, "weird", mac="not-a-mac")
    assert nics.collect(sys_net=tmp_path) == []
