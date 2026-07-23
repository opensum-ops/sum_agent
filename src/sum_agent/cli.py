"""CLI entrypoint: ``sum-agent enroll | run | inventory | version``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import structlog

from sum_agent import __version__
from sum_agent.core import state as state_mod
from sum_agent.core.errors import (
    AgentError,
    NotEnrolledError,
    ServerError,
    StateCorruptedError,
    TransportError,
)
from sum_agent.core.logging import configure_logging
from sum_agent.settings import get_settings, require_server_url

log = structlog.get_logger(__name__)

EXIT_OK = 0
EXIT_USAGE = 64
EXIT_DATAERR = 65
EXIT_UNAVAILABLE = 69


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sum-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_enroll = sub.add_parser("enroll", help="enroll with the server")
    p_enroll.add_argument("--server-url", help="override SUM_AGENT_SERVER_URL")
    p_enroll.add_argument("--token", required=True, help="one-time enrollment token")

    sub.add_parser("run", help="run the agent daemon")

    p_inv = sub.add_parser("inventory", help="print one-shot inventory JSON")
    p_inv.add_argument("--pretty", action="store_true")

    sub.add_parser("version", help="print package version")

    return parser


async def _cmd_enroll(args: argparse.Namespace) -> int:
    from sum_agent import client

    settings = get_settings()
    server_url = args.server_url or settings.server_url
    if not server_url:
        print("error: --server-url or SUM_AGENT_SERVER_URL is required", file=sys.stderr)
        return EXIT_USAGE
    new_state = await client.enroll(
        server_url=server_url, enrollment_token=args.token, settings=settings
    )
    path = state_mod.save(settings.state_dir, new_state)
    print(f"enrolled (host_id={new_state.host_id}); state at {path}")
    return EXIT_OK


async def _cmd_run(_args: argparse.Namespace) -> int:
    from sum_agent.runner import run as runner_run

    settings = get_settings()
    require_server_url(settings)
    try:
        state = state_mod.load(settings.state_dir)
    except NotEnrolledError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except StateCorruptedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DATAERR
    await runner_run(state, settings)
    return EXIT_OK


async def _cmd_inventory(args: argparse.Namespace) -> int:
    from sum_agent.inventory.snapshot import build

    snapshot = await build()
    indent = 2 if args.pretty else None
    json.dump(snapshot, sys.stdout, default=str, indent=indent, sort_keys=True)
    sys.stdout.write("\n")
    return EXIT_OK


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    if args.cmd == "version":
        return _cmd_version(args)

    handlers = {
        "enroll": _cmd_enroll,
        "run": _cmd_run,
        "inventory": _cmd_inventory,
    }
    handler = handlers[args.cmd]
    try:
        return asyncio.run(handler(args))
    except ServerError as exc:
        print(
            f"error: server returned {exc.http_status} {exc.code}: {exc.message}",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE
    except TransportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_DATAERR
    except KeyboardInterrupt:
        return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
