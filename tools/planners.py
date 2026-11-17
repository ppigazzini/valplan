"""Run valplan's planner and valgebra-planning's on the same tasks; write or check the counts.

    uv run python tools/planners.py
    uv run python tools/planners.py --json docs/studies/planners.json
    uv run python tools/planners.py --check docs/studies/planners.json

Both planners search to depth 6 and try the first 16 bindings of a call, each one's default,
over contracts valgebra-planning's reader reads, and every program either finds is judged by
valgebra-planning's verifier. A row counts, for one task and one planner, whether a strong or a
weak program is found, its stops, its links proven and undecided, the cells of the planner's
own cut and how many are undecided, and the search states expanded. A failure to find a strong
program is the search's, under those bounds, and certifies nothing.

The tasks are the helpdesk library's, the parcel library's four that name no rule, and each
planner's own synthetic family at 8, 32 and 128 tools in three seeds: valplan's strings and
numbers families, and valgebra-planning's planted chain beside two kinds of distractor. Each
task set was written by one planner's author, so a comparison holds on these sets alone.

The census reads the reference servers' 66 tools apart: each planner's cut of them for a task
taking a string to a string, its cells and its undecided cells, since the census holds no task
a program could solve. Times are printed and not recorded.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from census import SERVERS
from valgebra_planning.cells import abstract
from valgebra_planning.contracts import read_contract
from valgebra_planning.contracts import read_task as planning_task
from valgebra_planning.planner import plan, predicates
from valgebra_planning.verify import verify as planning_verify

from valplan.bench import library as valplan_library
from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.synth import Planner, witnesses
from valplan.verify import verify

FORMAT = 1
ROOT = Path(__file__).resolve().parent.parent
SIZES = (8, 32, 128)
SEEDS = (0, 1, 2)
DEPTH = 6
CHAIN = 4


def _id(prefix: str) -> dict[str, str]:
    return {"type": "string", "pattern": f"^{prefix}_[0-9]+$"}


def _tool(name: str, takes: str, gives: str) -> dict[str, Any]:
    record = {"type": "object", "properties": {"id": _id(gives)}, "required": ["id"]}
    arguments = {"type": "object", "properties": {"id": _id(takes)}, "required": ["id"]}
    return {"name": name, "inputSchema": arguments, "outputSchema": record}


def chain_library(size: int, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return valgebra-planning's synthetic family: a chain of four beside two distractors.

    The family of valgebra-planning's own suite (`tests/synthetic.py` there), rewritten here:
    a chain from the input to the goal, tools taking an identifier no held value can match, and
    tools taking the input whose results nothing reads, in a seeded order.
    """
    tools = [_tool(f"step{i}", f"k{i}", f"k{i + 1}") for i in range(CHAIN)]
    tools += [
        _tool(f"stray{i}", f"d{i}", f"e{i}") if i % 2 else _tool(f"dead{i}", "k0", f"z{i}")
        for i in range(size - CHAIN)
    ]
    random.Random(seed).shuffle(tools)
    inputs = {"type": "object", "properties": {"start": _id("k0")}, "required": ["start"]}
    return {"tools": tools}, {"name": "reach the end", "inputs": inputs, "goal": _id(f"k{CHAIN}")}


def _libraries() -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    found = []
    for name in ("helpdesk", "parcels"):
        directory = ROOT / "examples" / name
        listing = json.loads((directory / "tools.json").read_text(encoding="utf-8"))
        specs = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))["tasks"]
        found.append((name, listing, specs))
    for size in SIZES:
        for seed in SEEDS:
            for family in ("strings", "numbers"):
                listing, spec = valplan_library(size, seed, family)
                found.append((f"valplan {family} {size}/{seed}", listing, [spec]))
            listing, spec = chain_library(size, seed)
            found.append((f"valgebra-planning chain {size}/{seed}", listing, [spec]))
    return found


def _valplan_row(listing: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], float]:
    lib, task = read_tools(listing), read_task(spec)
    start = time.perf_counter()
    planner = Planner(lib, task, witnesses(lib, task))
    program = planner.plan(DEPTH, weak=True)
    took = time.perf_counter() - start
    checks = verify(lib, task, program) if program is not None else []
    links = [c for c in checks if c.relation != "uncovered"]
    counts = planner.abstraction.counts()
    return {
        "program": "none" if program is None else "weak" if planner.weak else "strong",
        "stops": len(checks) - len(links),
        "links": len(links),
        "proven": sum(c.holds for c in links),
        "undecided links": sum(c.relation == "undecided" for c in links),
        "cells": counts["cells"],
        "undecided cells": counts["undecided"],
        "expanded": planner.expanded,
    }, took


def _planning_row(listing: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], float]:
    contracts = {tool["name"]: read_contract(tool) for tool in listing["tools"]}
    held = {name: spec["inputs"]["properties"][name] for name in spec["inputs"]["required"]}
    task = planning_task(spec["name"], held, spec["goal"])
    start = time.perf_counter()
    found = plan(contracts, task, depth=DEPTH)
    took = time.perf_counter() - start
    checked = planning_verify(found.program, contracts, task) if found.program else None
    links = checked.links if checked else ()
    cells = found.abstraction.cells
    return {
        "program": "none" if found.program is None else "strong" if found.strong else "weak",
        "stops": len(checked.gaps) if checked else 0,
        "links": len(links),
        "proven": sum(link.verdict == "proven" for link in links),
        "undecided links": sum(link.verdict == "undecided" for link in links),
        "cells": len(cells),
        "undecided cells": sum(cell.status == "undecided" for cell in cells),
        "expanded": found.expanded,
    }, took


def _census() -> list[dict[str, Any]]:
    """Return each planner's cut of the reference servers' tools, for a string to a string.

    valgebra-planning's is read as `tools/census.py` reads it, so its counts are that study's;
    valplan's reads the same tools, each named by its server, since its names must be distinct.
    """
    tools, contracts = [], {}
    # In the census's order: the cut's undecided cells depend on the order its predicates are
    # split by, so another order is another count.
    for server in SERVERS:
        stored = json.loads((ROOT / "examples" / "census" / f"{server}.json").read_text("utf-8"))
        for tool in stored["tools"]:
            contracts[f"{stored['server']}.{tool['name']}"] = read_contract(tool)
            tools.append({**tool, "name": f"{stored['server']}.{tool['name']}"})
    goal = {"type": "string"}
    cut = abstract(
        predicates(contracts, planning_task("a string to a string", {"text": goal}, goal))
    )
    text = {"type": "object", "properties": {"text": goal}, "required": ["text"]}
    lib = read_tools({"tools": tools})
    task = read_task({"name": "a string to a string", "inputs": text, "goal": goal})
    counts = Planner(lib, task, witnesses(lib, task)).abstraction.counts()
    return [
        {
            "planner": "valgebra-planning",
            "predicates": len(cut.predicates),
            "cells": len(cut.cells),
            "undecided cells": sum(c.status == "undecided" for c in cut.cells),
        },
        {
            "planner": "valplan",
            "predicates": counts["predicates"],
            "cells": counts["cells"],
            "undecided cells": counts["undecided"],
        },
    ]


def study() -> tuple[dict[str, Any], list[str]]:
    """Return the study and a line of times for each task."""
    rows, times = [], []
    for name, listing, specs in _libraries():
        for spec in specs:
            for planner, run in (("valplan", _valplan_row), ("valgebra-planning", _planning_row)):
                row, took = run(listing, spec)
                rows.append({"library": name, "task": spec["name"], "planner": planner, **row})
                times.append(f"{name} / {spec['name']} / {planner}: {took:.3f} s")
    return {"format": FORMAT, "rows": rows, "census": _census()}, times


def main(argv: list[str]) -> int:
    """Run the study, then print, write or check it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    result, times = study()
    print("\n".join(times))
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
