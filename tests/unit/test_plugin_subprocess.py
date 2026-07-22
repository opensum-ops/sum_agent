"""End-to-end plugin subprocess test using an inline Python script as the plugin.

Exercises the JSON-RPC framing (request/response + a plugin -> agent progress
notification) without any network or signature concerns.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from sum_agent.plugins.cache import PluginEntry
from sum_agent.plugins.runtime import run

_PLUGIN_SOURCE = """\
#!{python}
import json, sys, time

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

# Plugin -> agent notification (no id, no result).
emit({"jsonrpc": "2.0", "method": "progress", "params": {"percent": 50, "note": "halfway"}})

# Read one request.
line = sys.stdin.readline()
msg = json.loads(line)
emit({
    "jsonrpc": "2.0",
    "id": msg["id"],
    "result": {
        "status": "completed",
        "exit_code": 0,
        "output": {"echo": msg["params"]["payload"], "capability": msg["params"]["capability"]},
    },
})
"""


def _write_plugin(tmp_path: Path) -> PluginEntry:
    plugin_dir = tmp_path / "demo-1.0.0"
    plugin_dir.mkdir()
    entry = plugin_dir / "run.py"
    entry.write_text(_PLUGIN_SOURCE.replace("{python}", sys.executable))
    os.chmod(entry, os.stat(entry).st_mode | stat.S_IXUSR)
    return PluginEntry(
        name="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        entrypoint=entry,
        capabilities=("plugin.demo",),
    )


async def test_runs_inline_python_plugin(tmp_path: Path) -> None:
    entry = _write_plugin(tmp_path)
    outcome = await run(entry, capability="plugin.demo", payload={"k": "v"}, timeout_seconds=10)
    assert outcome["status"] == "completed"
    assert outcome["output"] == {"echo": {"k": "v"}, "capability": "plugin.demo"}
