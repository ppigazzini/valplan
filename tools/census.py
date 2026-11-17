"""Count what valgebra-planning reads of the tools the MCP reference servers list.

    uv run --no-sync python tools/census.py
    uv run --no-sync python tools/census.py --json docs/studies/census.json
    uv run --no-sync python tools/census.py --check docs/studies/census.json
    uv run --no-sync python tools/census.py --refresh --check docs/studies/census.json

The listings are stored, one file a server under ``examples/census/``, each the ``tools/list``
result of the release ``SERVERS`` pins. A count reads the stored listings alone, with no network,
so it reproduces wherever the commit does: each tool is read as a contract, and every argument
and result is cut into cells together, as the planner cuts them for a task taking a string to a
string. A row counts what a server lists and what it carries a planner can use; the total counts
the cells, the undecided ones, and the relations the cut asked of valgebra, the cost a change to
the cells moves.

``--refresh`` starts each server over stdio with ``uvx`` or ``npx``, asks ``tools/list`` through
the MCP client, rewrites its file and then counts. A pinned server is not a pinned listing: a
server's own dependencies resolve when it starts, and its SDK writes the schemas, so a listing can
move under an unchanged pin, and ``--refresh --check`` reports it. It needs the network and the
``mcp`` extra.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from valgebra_planning.cells import abstract
from valgebra_planning.contracts import Contract, read_contract, read_task
from valgebra_planning.planner import predicates

FORMAT = 1
ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "examples" / "census"
#: Each server and the release read; a new release is a new study.
SERVERS = {
    "time": ("uvx", ["mcp-server-time==2026.11.4"]),
    "fetch": ("uvx", ["mcp-server-fetch==2026.11.4"]),
    "git": ("uvx", ["mcp-server-git==2026.11.4", "--repository", str(ROOT)]),
    "everything": ("npx", ["-y", "@modelcontextprotocol/server-everything@2.2.1"]),
    "filesystem": ("npx", ["-y", "@modelcontextprotocol/server-filesystem@2.2.0", "{scratch}"]),
    "memory": ("npx", ["-y", "@modelcontextprotocol/server-memory@2.1.0"]),
    "sequential-thinking": (
        "npx",
        ["-y", "@modelcontextprotocol/server-sequential-thinking@2.1.1"],
    ),
}
#: Keywords that describe a property without narrowing it.
DESCRIBING = frozenset({"type", "description", "title", "default"})


async def _listing(command: str, arguments: list[str]) -> list[dict[str, Any]]:
    from mcp import Client, StdioServerParameters  # noqa: PLC0415 - only a refresh starts one

    async with Client(StdioServerParameters(command=command, args=arguments)) as client:
        listed = await client.list_tools()
        return [
            tool.model_dump(by_alias=True, exclude_none=True, mode="json") for tool in listed.tools
        ]


def _release(server: str) -> str:
    command, arguments = SERVERS[server]
    return arguments[1 if command == "npx" else 0]


def refresh() -> None:
    """Read every server's listing live, and store it."""
    with tempfile.TemporaryDirectory() as scratch:
        for server, (command, arguments) in SERVERS.items():
            argv = [argument.replace("{scratch}", scratch) for argument in arguments]
            listing = asyncio.run(_listing(command, argv))
            stored = {"server": server, "release": _release(server), "tools": listing}
            text = json.dumps(stored, indent=2, ensure_ascii=False) + "\n"
            (LISTINGS / f"{server}.json").write_text(text, encoding="utf-8")


def _stored(server: str) -> list[dict[str, Any]]:
    stored = json.loads((LISTINGS / f"{server}.json").read_text(encoding="utf-8"))
    if stored["release"] != _release(server):
        # Refuse a listing of another release: its counts would be published as this one's.
        message = f"{server}: the stored listing is {stored['release']}, SERVERS pins "
        raise SystemExit(message + f"{_release(server)}; run --refresh")
    return stored["tools"]


def _row(server: str, listing: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Contract]]:
    contracts = {f"{server}.{tool['name']}": read_contract(tool) for tool in listing}
    properties = [p for tool in listing for p in tool["inputSchema"].get("properties", {}).values()]
    return {
        "server": server,
        "release": _release(server),
        "tools": len(listing),
        "output schemas": sum("outputSchema" in tool for tool in listing),
        "read": len(contracts),
        "arguments": sum(len(c.arguments) for c in contracts.values()),
        "bare arguments": sum(not set(p) - DESCRIBING for p in properties),
        "result slots": sum(len(c.results) for c in contracts.values()),
    }, contracts


def study() -> dict[str, Any]:
    """Return the census of every server's stored listing."""
    rows, contracts, outputs = [], {}, set()
    for server in SERVERS:
        listing = _stored(server)
        row, read = _row(server, listing)
        rows.append(row)
        contracts |= read
        outputs |= {
            json.dumps(t["outputSchema"], sort_keys=True) for t in listing if "outputSchema" in t
        }
    task = read_task("a string to a string", {"text": {"type": "string"}}, {"type": "string"})
    cut = abstract(predicates(contracts, task))
    undecided = [cell for cell in cut.cells if cell.status == "undecided"]
    total = {
        "tools": sum(row["tools"] for row in rows),
        "output schemas": sum(row["output schemas"] for row in rows),
        "distinct output schemas": len(outputs),
        "predicates": len(cut.predicates),
        "cells": len(cut.cells),
        "undecided cells": len(undecided),
        "undecided array cells": sum(cell.kind == "array" for cell in undecided),
        "relations asked": cut.asked,
    }
    return {"format": FORMAT, "rows": rows, "total": total}


def main(argv: list[str]) -> int:
    """Take the census, then print, write or check it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    parser.add_argument("--refresh", action="store_true", help="read each listing live first")
    args = parser.parse_args(argv)
    if args.refresh:
        refresh()
    result = study()
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.check:
        published = json.loads(args.check.read_text(encoding="utf-8"))
        if published != result:
            print(f"\nthe counts differ from {args.check}")
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
