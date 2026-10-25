"""Plan on synthetic libraries of growing size; print counts and times, write or check the study.

    uv run python tools/bench.py
    uv run python tools/bench.py --json docs/studies/bench.json
    uv run python tools/bench.py --check docs/studies/bench.json

The study records counts only. Times are printed beside them and are this machine's: a
time is not a reproducible number, a count of expanded search nodes is.
"""

import argparse
import sys
import time
from pathlib import Path

from valplan.bench import library
from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.program import Test, calls
from valplan.study import BENCH, BenchRow, BenchStudy, dumps, load_bench
from valplan.synth import Planner, witnesses
from valplan.verify import verify

SIZES = (8, 16, 32, 64, 128, 256)
SEEDS = (0, 1, 2)
FAMILIES = ("strings", "numbers")
DEPTH = 6


def _tests(program: tuple) -> int:
    return sum(1 + _tests(s.then) + _tests(s.other) for s in program if isinstance(s, Test))


def measure(sizes: tuple[int, ...], seeds: tuple[int, ...]) -> tuple[BenchStudy, list[str]]:
    """Run every family, size and seed; return the study and one timing line per row."""
    rows: list[BenchRow] = []
    times: list[str] = []
    for family, n, seed in ((f, n, s) for f in FAMILIES for n in sizes for s in seeds):
        lib_json, spec = library(n, seed, family)
        lib, task = read_tools(lib_json), read_task(spec)
        t0 = time.perf_counter()
        planner = Planner(lib, task, witnesses(lib, task))
        t1 = time.perf_counter()
        program = planner.plan(max_depth=DEPTH)
        t2 = time.perf_counter()
        checks = verify(lib, task, program) if program else []
        counts = planner.abstraction.counts()
        rows.append(
            BenchRow(
                family="strings" if family == "strings" else "numbers",
                tools=n,
                seed=seed,
                predicates=counts["predicates"],
                cells=counts["cells"],
                inhabited=counts["inhabited"],
                undecided=counts["undecided"],
                found=program is not None,
                calls=calls(program) if program else 0,
                tests=_tests(program) if program else 0,
                checks=len(checks),
                proven=sum(c.holds for c in checks),
                expanded=planner.expanded,
            )
        )
        times.append(f"{n} tools, seed {seed}: abstraction {t1 - t0:.2f} s, search {t2 - t1:.2f} s")
    return BenchStudy(format=1, max_depth=DEPTH, rows=rows), times


def table(study: BenchStudy) -> str:
    """Render one row per library."""
    head = "| family | tools | seed | predicates | cells (undecided) | found | calls | tests |"
    lines = [f"{head} proven | expanded |", "|---|---:|---:|---:|---|---|---:|---:|---|---:|"]
    lines += [
        f"| {r['family']} | {r['tools']} | {r['seed']} | {r['predicates']} "
        f"| {r['cells']} ({r['undecided']}) | {'yes' if r['found'] else 'no'} "
        f"| {r['calls']} | {r['tests']} "
        f"| {r['proven']} of {r['checks']} | {r['expanded']} |"
        for r in study["rows"]
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Measure, then print, write or check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    study, times = measure(SIZES, SEEDS)
    print(table(study))
    print()
    print("\n".join(times))
    if args.json:
        args.json.write_text(dumps(study, BENCH), encoding="utf-8")
    if args.check:
        expected = load_bench(args.check.read_text(encoding="utf-8"))
        if expected != study:
            print(f"\nthe counts differ from {args.check}", file=sys.stderr)
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
