"""Plan on synthetic libraries of growing size; print counts and times, write or check the study.

    uv run python tools/bench.py
    uv run python tools/bench.py --json docs/studies/bench.json
    uv run python tools/bench.py --check docs/studies/bench.json

The study records counts only. Times are printed beside them and are this machine's: a
time is not a reproducible number, a count of expanded search nodes is. The libraries run
in parallel, one worker process per core by default (``--jobs``).
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
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


def run_one(job: tuple[str, int, int]) -> tuple[BenchRow, str]:
    """Build, plan and verify one library; return its row and a timing line.

    A module-level function of three integers and a name, so a worker process can run it:
    valgebra validators are built inside the worker, never sent to it.
    """
    family, n, seed = job
    lib_json, spec = library(n, seed, family)
    lib, task = read_tools(lib_json), read_task(spec)
    t0 = time.perf_counter()
    planner = Planner(lib, task, witnesses(lib, task))
    t1 = time.perf_counter()
    program = planner.plan(max_depth=DEPTH)
    t2 = time.perf_counter()
    checks = verify(lib, task, program) if program else []
    counts = planner.abstraction.counts()
    row = BenchRow(
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
    line = f"{family}, {n} tools, seed {seed}: abstraction {t1 - t0:.2f} s, search {t2 - t1:.2f} s"
    return row, line


def measure(
    sizes: tuple[int, ...], seeds: tuple[int, ...], jobs: int = 1
) -> tuple[BenchStudy, list[str]]:
    """Run every family, size and seed; return the study and one timing line per row.

    The libraries are independent, so ``jobs`` worker processes run them side by side;
    `Executor.map` returns the rows in submission order, so the study is the same whatever
    the number of workers.
    """
    todo = [(f, n, s) for f in FAMILIES for n in sizes for s in seeds]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            done = list(pool.map(run_one, todo))
    else:
        done = [run_one(job) for job in todo]
    rows = [row for row, _ in done]
    return BenchStudy(format=1, max_depth=DEPTH, rows=rows), [line for _, line in done]


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
    parser.add_argument(
        "--jobs", type=int, default=os.process_cpu_count() or 1, help="worker processes"
    )
    args = parser.parse_args(argv)
    study, times = measure(SIZES, SEEDS, args.jobs)
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
