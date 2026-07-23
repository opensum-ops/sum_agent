"""Fact collector unit tests (injectable paths, no live system dependency)."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from sum_agent.inventory import facts_network, facts_os, facts_system

OS_RELEASE_SAMPLE = """\
PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"
NAME="Debian GNU/Linux"
VERSION_ID="12"
VERSION="12 (bookworm)"
ID=debian
HOME_URL="https://www.debian.org/"
# comment line
BROKEN-LINE-WITHOUT-EQUALS
"""

ROUTE_SAMPLE = """\
Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
ens18\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0
ens18\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
"""


def test_parse_os_release() -> None:
    fields = facts_os.parse_os_release(OS_RELEASE_SAMPLE)
    assert fields["ID"] == "debian"
    assert fields["NAME"] == "Debian GNU/Linux"
    assert fields["VERSION_ID"] == "12"
    assert "BROKEN-LINE-WITHOUT-EQUALS" not in fields


def test_facts_os_collect(tmp_path: Path) -> None:
    osr = tmp_path / "os-release"
    osr.write_text(OS_RELEASE_SAMPLE, encoding="utf-8")
    facts = facts_os.collect(os_release=osr)
    assert facts["os_id"] == "debian"
    assert facts["os_name"] == "Debian GNU/Linux"
    assert facts["os_version"] == "12"
    assert facts["kernel"]  # from uname; non-empty on any Linux


def test_facts_os_collect_missing_file(tmp_path: Path) -> None:
    facts = facts_os.collect(os_release=tmp_path / "nope")
    assert "os_id" not in facts
    assert facts["kernel"]


def test_default_iface_from_route() -> None:
    assert facts_network.default_iface_from_route(ROUTE_SAMPLE) == "ens18"
    assert facts_network.default_iface_from_route("Iface\tDestination\n") is None


class _Addr:
    def __init__(self, family: int, address: str) -> None:
        self.family = family
        self.address = address


def test_facts_network_collect(tmp_path: Path) -> None:
    route = tmp_path / "route"
    route.write_text(ROUTE_SAMPLE, encoding="utf-8")

    def fake_addrs() -> dict[str, list[Any]]:
        return {
            "ens18": [
                _Addr(socket.AF_INET, "192.168.1.10"),
                _Addr(socket.AF_INET6, "fe80::1%ens18"),
                _Addr(socket.AF_INET6, "2001:db8::10"),
            ]
        }

    facts = facts_network.collect(route_path=route, if_addrs=fake_addrs)
    assert facts == {
        "default_iface": "ens18",
        "primary_ipv4": "192.168.1.10",
        "primary_ipv6": "2001:db8::10",
    }


def test_facts_network_no_default_route(tmp_path: Path) -> None:
    route = tmp_path / "route"
    route.write_text("Iface\tDestination\n", encoding="utf-8")
    assert facts_network.collect(route_path=route, if_addrs=dict) == {}


def test_facts_system_collect(tmp_path: Path) -> None:
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("abc123\n", encoding="utf-8")
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("6ba7b810-9dad-11d1-80b4-00c04fd430c8\n", encoding="utf-8")
    facts = facts_system.collect(machine_id_path=machine_id, boot_id_path=boot_id)
    assert facts["hostname"]
    assert facts["arch"]
    assert facts["machine_id"] == "abc123"
    assert facts["boot_id"] == "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    assert "boot_time" in facts


def test_read_boot_id_missing(tmp_path: Path) -> None:
    assert facts_system.read_boot_id(boot_id_path=tmp_path / "nope") is None
