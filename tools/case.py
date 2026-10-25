"""Plan every task of a tool library, verify each program, print them, write or check the study.

    uv run python tools/case.py examples/helpdesk
    uv run python tools/case.py examples/helpdesk --json docs/studies/helpdesk.json
    uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json

A library directory holds ``tools.json`` (an MCP ``tools/list`` result) and ``tasks.json``.
"""

import argparse
import json
import sys
from pathlib import Path

from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.program import Program, Test, calls, render, stops
from valplan.study import CASE, CaseStudy, TaskRow, dumps, load_case
from valplan.synth import Planner, gaps, witnesses
from valplan.verify import verify


def tests_in(program: Program) -> int:
    """Return the number of runtime tests in ``program``."""
    return sum(1 + tests_in(s.then) + tests_in(s.other) for s in program if isinstance(s, Test))


def measure(library: Path) -> tuple[CaseStudy, list[str]]:
    """Plan and verify every task; return the study and the rendered programs."""
    lib = read_tools(json.loads((library / "tools.json").read_text(encoding="utf-8")))
    specs = json.loads((library / "tasks.json").read_text(encoding="utf-8"))["tasks"]
    rows: list[TaskRow] = []
    shown: list[str] = []
    for spec in specs:
        task = read_task(spec)
        planner = Planner(lib, task, witnesses(lib, task))
        program = planner.plan(max_depth=6, weak=True) or ()
        checks = verify(lib, task, program) if program else []
        counts = planner.abstraction.counts()
        rows.append(
            TaskRow(
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
        )
        kind = "strong" if rows[-1]["strong"] else "weak"
        text = f"## {task.name} ({kind})\n\n```\n{render(program)}\n```"
        uncovered = [
            f"- uncovered at step {g.path}: {g.describe()}" for g in gaps(planner, program)
        ]
        shown.append("\n\n".join([text, *(["\n".join(uncovered)] if uncovered else [])]))
    return CaseStudy(format=1, library=library.name, tools=len(lib), tasks=rows), shown


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
    args = parser.parse_args(argv)
    study, shown = measure(args.library)
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
