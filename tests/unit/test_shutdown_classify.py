"""Shutdown classification against canned ``systemctl list-jobs`` output."""

from __future__ import annotations

import subprocess

from sum_agent.core.shutdown import AGENT_STOP, POWERED_OFF, REBOOTING, classify_shutdown


def test_reboot_target_detected() -> None:
    out = "123 reboot.target start waiting\n124 sum-agent.service stop running\n"
    assert classify_shutdown(list_jobs=lambda: out) == REBOOTING


def test_poweroff_target_detected() -> None:
    out = "77 poweroff.target start waiting\n"
    assert classify_shutdown(list_jobs=lambda: out) == POWERED_OFF


def test_halt_target_detected() -> None:
    out = "9 halt.target start waiting\n"
    assert classify_shutdown(list_jobs=lambda: out) == POWERED_OFF


def test_plain_stop_is_agent_stop() -> None:
    assert classify_shutdown(list_jobs=lambda: "") == AGENT_STOP
    out = "5 some-other.service stop running\n"
    assert classify_shutdown(list_jobs=lambda: out) == AGENT_STOP


def test_failure_is_agent_stop() -> None:
    def boom() -> str:
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

    assert classify_shutdown(list_jobs=boom) == AGENT_STOP


def test_reboot_wins_over_poweroff_ordering() -> None:
    # Defensive: if both ever appear, reboot is the more specific signal.
    out = "1 reboot.target start waiting\n2 poweroff.target start waiting\n"
    assert classify_shutdown(list_jobs=lambda: out) == REBOOTING
