from __future__ import annotations

import json

from sum_agent.inventory import disks

LSBLK_SAMPLE = json.dumps(
    {
        "blockdevices": [
            {
                "name": "nvme0n1",
                "vendor": "Samsung",
                "model": "PM9A3",
                "serial": "S6KZNX0T123456",
                "size": 1_920_383_410_176,
                "rota": 0,
                "type": "disk",
                "tran": "nvme",
                "wwn": "0x5002538f00000000",
            },
            {
                "name": "sda",
                "vendor": "ATA",
                "model": "Hitachi",
                "serial": "ABC123",
                "size": 1_000_204_886_016,
                "rota": 1,
                "type": "disk",
                "tran": "sata",
            },
            {
                "name": "sr0",
                "type": "rom",
            },
        ]
    }
)


def test_parse_disks_only() -> None:
    out = disks.parse(LSBLK_SAMPLE)
    assert len(out) == 2
    nvme = next(d for d in out if d["slot"] == "nvme0n1")
    assert nvme["attrs"]["bus"] == "nvme"
    assert nvme["attrs"]["rotation_rpm"] == 0
    assert nvme["attrs"]["size_bytes"] == 1_920_383_410_176

    sata = next(d for d in out if d["slot"] == "sda")
    assert sata["attrs"]["bus"] == "sata"
    assert sata["attrs"]["rotation_rpm"] == 7200
    assert sata["attrs"]["wwn"] is None
