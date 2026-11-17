"""Cut one list of predicates with valplan's cell rules and with valgebra-planning's cut.

    uv run python tools/rules.py
    uv run python tools/rules.py --json docs/studies/rules.json
    uv run python tools/rules.py --check docs/studies/rules.json

The predicates are the ones valgebra-planning's planner cuts for a task (its `predicates`), in
the order of their names, so both cuts read the same sets. valgebra-planning's `abstract` cuts
them, and valplan's abstraction cuts them bare, with each of its three rules alone, and with all
three: listed values deciding a finite cell, interval arithmetic deciding a range cell, and a
union's cell asked branch by branch. Every valplan cut is handed one pool of members, drawn from
each predicate's schema by a stream seeded by its names. A row counts the cells a cut keeps,
those it cannot prove empty, and how many of them hold no member found, the undecided ones: the
first measures what a rule proves empty, the second what is left unknown.

The tasks are the census's, a string to a string over the reference servers' 66 tools, and
valplan's numbers family at 32 and 64 tools, seed 0, whose ranges are what the interval rule
reads; at 128 tools valplan's cut without that rule runs past 150 s, so no count of it is
recorded. Times are printed and not recorded.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

from census import SERVERS
from valgebra_jsonschema import Compiler, Unsupported, branches, finite, interval
from valgebra_jsonschema.sample import Sampler
from valgebra_planning.cells import Predicate, abstract
from valgebra_planning.contracts import read_contract, read_task
from valgebra_planning.planner import predicates

from valplan.abstraction import Abstraction
from valplan.bench import library

FORMAT = 1
ROOT = Path(__file__).resolve().parent.parent
#: Members drawn from each predicate's schema for valplan's cuts.
DRAWS = 24
RULES = ("bare", "listed", "intervals", "union branches", "all")


def _census() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    tools = []
    for server in SERVERS:
        stored = json.loads((ROOT / "examples" / "census" / f"{server}.json").read_text("utf-8"))
        tools += [{**tool, "name": f"{server}.{tool['name']}"} for tool in stored["tools"]]
    return tools, {"text": {"type": "string"}}, {"type": "string"}


def _numbers(size: int) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    listing, spec = library(size, 0, "numbers")
    held = {name: spec["inputs"]["properties"][name] for name in spec["inputs"]["required"]}
    return listing["tools"], held, spec["goal"]


def _predicates(
    tools: list[dict[str, Any]], held: dict[str, Any], goal: dict[str, Any]
) -> list[Predicate]:
    contracts = {tool["name"]: read_contract(tool) for tool in tools}
    found = predicates(contracts, read_task("task", held, goal))
    return sorted(found, key=lambda predicate: sorted(predicate.names))


def _pool(found: list[Predicate]) -> list[Any]:
    pool: list[Any] = []
    for predicate in found:
        rng = random.Random(f"0:{','.join(sorted(predicate.names))}")
        try:
            pool += Sampler(predicate.root, rng).draw(predicate.schema, DRAWS)
        except Unsupported, RecursionError:
            continue
    return pool


def _valplan(found: list[Predicate], pool: list[Any], rule: str) -> Abstraction:
    sets = [p.values for p in found]
    listed = {p.values: v for p in found if (v := finite(p.schema, p.root)) is not None}
    ranges = {p.values: r for p in found if (r := interval(p.schema)) is not None}
    unions = {}
    for p in found:
        if (parts := branches(p.schema)) is not None:
            compiler = Compiler(p.root)
            unions[p.values] = [compiler.compile(part) for part in parts]
    return Abstraction(
        sets,
        pool,
        finite=listed if rule in ("listed", "all") else None,
        ranges=ranges if rule in ("intervals", "all") else None,
        unions=unions if rule in ("union branches", "all") else None,
    )


def study() -> tuple[dict[str, Any], list[str]]:
    """Return the study and a line of times for each cut."""
    rows, times = [], []
    tasks = {"census": _census(), "numbers 32": _numbers(32), "numbers 64": _numbers(64)}
    for name, task in tasks.items():
        found = _predicates(*task)
        start = time.perf_counter()
        cut = abstract(found)
        times.append(f"{name} / valgebra-planning: {time.perf_counter() - start:.2f} s")
        undecided = sum(cell.status == "undecided" for cell in cut.cells)
        base = {"task": name, "predicates": len(found)}
        rows.append(
            {**base, "cut": "valgebra-planning", "cells": len(cut.cells), "undecided": undecided}
        )
        pool = _pool(found)
        for rule in RULES:
            start = time.perf_counter()
            counts = _valplan(found, pool, rule).counts()
            times.append(f"{name} / valplan {rule}: {time.perf_counter() - start:.2f} s")
            cells, undecided = counts["cells"], counts["undecided"]
            rows.append({**base, "cut": f"valplan {rule}", "cells": cells, "undecided": undecided})
    return {"format": FORMAT, "rows": rows}, times


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
