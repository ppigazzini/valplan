"""Plan every task of a tool library, verify each program, print them, write or check the study.

    uv run python tools/case.py examples/helpdesk
    uv run python tools/case.py examples/helpdesk --json docs/studies/helpdesk.json
    uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json

A library directory holds ``tools.json`` (an MCP ``tools/list`` result) and ``tasks.json``.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.program import Program, Test, calls, render, stops
from valplan.study import CASE, CaseStudy, TaskRow, dumps, load_case
from valplan.synth import Planner, gaps, witnesses
from valplan.verify import verify


def tests_in(program: Program) -> int:
    """Return the number of runtime tests in ``program``."""
    return sum(1 + tests_in(s.then) + tests_in(s.other) for s in program if isinstance(s, Test))


def run_task(job: tuple[Path, dict[str, Any]]) -> tuple[TaskRow, str]:
    """Plan and verify one task; return its row and its rendered program."""
    library, spec = job
    lib = read_tools(json.loads((library / "tools.json").read_text(encoding="utf-8")))
    task = read_task(spec)
    drawn = witnesses(lib, task)
    planner = Planner(lib, task, drawn)
    program = planner.plan(max_depth=6, weak=True) or ()
    checks = verify(lib, task, program, drawn) if program else []
    counts = planner.abstraction.counts()
    row = TaskRow(
        task=task.name,
        predicates=counts["predicates"],
        cells=counts["cells"],
        inhabited=counts["inhabited"],
        undecided=counts["undecided"],
        strong=bool(program) and not planner.weak,
        calls=calls(program),
        tests=tests_in(program),
        stops=stops(program) if program else 1,
        checks=len(checks),
        proven=sum(c.holds for c in checks),
        refuted=sum(c.relation == "not_subset" for c in checks),
    )
    kind = "strong" if row["strong"] else "weak"
    text = f"## {task.name} ({kind})\n\n```\n{render(program)}\n```"
    uncovered = [f"- uncovered at step {g.path}: {g.describe()}" for g in gaps(planner, program)]
    return row, "\n\n".join([text, *(["\n".join(uncovered)] if uncovered else [])])


def measure(library: Path, jobs: int = 1) -> tuple[CaseStudy, list[str]]:
    """Plan and verify every task, ``jobs`` at a time; return the study and the programs."""
    tools_count = len(json.loads((library / "tools.json").read_text(encoding="utf-8"))["tools"])
    specs = json.loads((library / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    todo = [(library, spec) for spec in specs]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            done = list(pool.map(run_task, todo))
    else:
        done = [run_task(job) for job in todo]
    rows = [row for row, _ in done]
    study = CaseStudy(format=1, library=library.name, tools=tools_count, tasks=rows)
    return study, [shown for _, shown in done]


def table(study: CaseStudy) -> str:
    """Render one row per task."""
    lines = [
        f"{study['library']}: {study['tools']} tools",
        "",
        "| task | cells (inhabited / undecided) | program | calls | tests | stops | proven |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for r in study["tasks"]:
        kind = "strong" if r["strong"] else "weak"
        lines.append(
            f"| {r['task']} | {r['cells']} ({r['inhabited']} / {r['undecided']}) | {kind} "
            f"| {r['calls']} | {r['tests']} | {r['stops']} | {r['proven']} of {r['checks']} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Measure, then print, write or check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("library", type=Path)
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    parser.add_argument(
        "--jobs", type=int, default=os.process_cpu_count() or 1, help="worker processes"
    )
    args = parser.parse_args(argv)
    study, shown = measure(args.library, args.jobs)
    print(table(study))
    print()
    print("\n\n".join(shown))
    if args.json:
        args.json.write_text(dumps(study, CASE), encoding="utf-8")
    if args.check:
        expected = load_case(args.check.read_text(encoding="utf-8"))
        if expected != study:
            print(f"\nthe counts differ from {args.check}", file=sys.stderr)
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
