"""PyInstaller entry shim for the frozen ``sum-agent`` binary.

PyInstaller freezes this module; it just hands off to the real CLI so the
single-file executable behaves exactly like ``sum-agent`` installed from the
wheel.
"""

from __future__ import annotations

import sys

from sum_agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
