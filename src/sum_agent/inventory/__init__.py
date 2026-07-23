"""Inventory collectors.

Importing this package registers every collector module with the framework in
``inventory/base.py``. To add a module: write it (see ``base.py`` for the
recipe) and import it here.
"""

from sum_agent.inventory import (  # noqa: F401  imports register the collectors
    cpu,
    disks,
    facts_agent,
    facts_network,
    facts_os,
    facts_system,
    gpu,
    memory,
    nics,
)
