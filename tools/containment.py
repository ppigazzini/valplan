"""Ask valgebra the inclusions of a containment test suite; print, write or check the study.

    uv run python tools/containment.py
    uv run python tools/containment.py --json docs/studies/containment.json
    uv run python tools/containment.py --check docs/studies/containment.json

The suite is the JSON Schema containment test suite (Attouche et al., 2021; MIT): pairs of
schemas generated from the JSON-Schema-Test-Suite, each labeling whether the first is a
subset of the second, the converse, or both. It is fetched at a pinned commit into
``results/``, which is not committed, and never vendored. Drafts 2020-12, 7, 6 and 4 are
read, the older ones through `upgrade`; of the optional files, the four the suite study
runs too, on regular expressions and large numbers.

Each labeled direction is asked with `relation_to` and counted as proven, refuted or
undecided, and against the label where a proof or a refutation contradicts it. A proof
against a label would be a wrong proof; a refutation against one, a wrong refutation or a
wrong label, and `docs/04-results.md` names each.
"""

import argparse
import io
import json
import os
import signal
import sys
import tarfile
import urllib.request
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any

from valplan._valgebra import Validator
from valplan.schema import Compiler, Unsupported, upgrade
from valplan.study import (
    CONTAINMENT,
    ContainmentRow,
    ContainmentStudy,
    dumps,
    load_containment,
)

ROOT = Path(__file__).parent.parent
SUITE = "sdbs-uni-p/json-schema-containment-testsuite"
COMMIT = "446fb41c527c8f8b2d2da1554e12fbc556c20a2e"
CACHE = ROOT / "results" / f"containment-{COMMIT[:12]}"
#: The draft directories read, by the name a row gives them, and the draft `upgrade` reads.
DRAFTS = {
    "2020-12": ("draft2020-12", None),
    "7": ("draft7", 7),
    "6": ("draft6", 6),
    "4": ("draft4", 4),
}
#: The optional files the suite study runs: regular expressions and large numbers.
OPTIONAL = frozenset({"bignum", "ecmascript-regex", "float-overflow", "non-bmp-regex"})
#: Seconds one question may take; none of the suite needs one.
TIMEOUT = 60
DIRECTIONS = (("s1SubsetEqOfs2", 0, 1), ("s2SubsetEqOfs1", 1, 0))


def fetch(cache: Path) -> None:
    """Download the suite at `COMMIT` and keep its test files, by their path under ``tests``."""
    url = f"https://codeload.github.com/{SUITE}/tar.gz/{COMMIT}"
    with urllib.request.urlopen(url, timeout=300) as response:
        archive = response.read()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = PurePosixPath(member.name).parts
            if member.isfile() and parts[1:2] == ("tests",) and member.name.endswith(".json"):
                member.name = "/".join(parts[2:])
                tar.extract(member, cache, filter="data")


def files(cache: Path, directory: str) -> list[Path]:
    """Return a draft's test files: every one outside ``optional/``, and the chosen optional."""
    return sorted(
        f
        for f in (cache / directory).rglob("*.json")
        if "optional" not in f.parts or (f.parent.name == "optional" and f.stem in OPTIONAL)
    )


def _compile(schema: object, older: int | None) -> Validator[Any]:
    document = upgrade(schema, older) if older is not None else schema
    return Compiler(document).compile(document)


class _OutOfTimeError(Exception):
    pass


def _alarm(*_: object) -> None:
    raise _OutOfTimeError


def one(job: tuple[str, Path]) -> tuple[str, str, Counter[str]]:
    """Ask every labeled direction of one test file; return its draft, category and counts."""
    draft, path = job
    older = DRAFTS[draft][1]
    signal.signal(signal.SIGALRM, _alarm)
    counts: Counter[str] = Counter()
    for pair in json.loads(path.read_text(encoding="utf-8")):
        labeled = [(key, a, b) for key, a, b in DIRECTIONS if key in pair["tests"]]
        counts["questions"] += len(labeled)
        try:
            schemas = [_compile(pair["schema1"], older), _compile(pair["schema2"], older)]
        except Unsupported:
            counts["refused"] += len(labeled)
            continue
        for key, a, b in labeled:
            signal.alarm(TIMEOUT)
            try:
                relation = schemas[a].relation_to(schemas[b])
            except _OutOfTimeError:
                counts["timed_out"] += 1
                continue
            finally:
                signal.alarm(0)
            label = pair["tests"][key]
            answer = {"subset": "proven", "not_subset": "refuted"}.get(relation, "undecided")
            counts[answer] += 1
            counts["proven_against"] += answer == "proven" and not label
            counts["refuted_against"] += answer == "refuted" and label
    parts = path.relative_to(CACHE / DRAFTS[draft][0]).parts
    return draft, parts[0], counts


def measure(cache: Path, jobs: int) -> ContainmentStudy:
    """Ask every draft's questions, ``jobs`` files at a time."""
    todo = [(draft, f) for draft, (directory, _) in DRAFTS.items() for f in files(cache, directory)]
    rows: dict[tuple[str, str], Counter[str]] = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for draft, category, counts in pool.map(one, todo, chunksize=4):
            rows.setdefault((draft, category), Counter()).update(counts)
    order = list(DRAFTS)
    return ContainmentStudy(
        format=1,
        suite=SUITE,
        commit=COMMIT,
        rows=[
            ContainmentRow(
                draft=draft,  # ty: ignore[invalid-argument-type]
                category=category,
                questions=c["questions"],
                refused=c["refused"],
                timed_out=c["timed_out"],
                proven=c["proven"],
                refuted=c["refuted"],
                undecided=c["undecided"],
                proven_against=c["proven_against"],
                refuted_against=c["refuted_against"],
            )
            for (draft, category), c in sorted(
                rows.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1])
            )
        ],
    )


def table(study: ContainmentStudy) -> str:
    """Render one row per draft and category, and a total per draft."""
    keys = ("questions", "refused", "timed_out", "proven", "refuted", "undecided")
    keys += ("proven_against", "refuted_against")
    lines = [
        f"{study['suite']} at {study['commit'][:12]}",
        "",
        "| draft | category | " + " | ".join(k.replace("_", " ") for k in keys) + " |",
        "|---|---|" + "---:|" * len(keys),
    ]
    all_rows: list[Any] = study["rows"]
    for draft in DRAFTS:
        rows = [r for r in all_rows if r["draft"] == draft]
        lines += [
            f"| {draft} | {r['category']} | " + " | ".join(str(r[k]) for k in keys) + " |"
            for r in rows
        ]
        totals = {k: sum(r[k] for r in rows) for k in keys}
        lines.append(f"| {draft} | all | " + " | ".join(str(totals[k]) for k in keys) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Fetch if needed, measure, then print, write or check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    parser.add_argument(
        "--jobs", type=int, default=os.process_cpu_count() or 1, help="worker processes"
    )
    args = parser.parse_args(argv)
    if not any(CACHE.rglob("*.json")):
        fetch(CACHE)
    study = measure(CACHE, args.jobs)
    print(table(study))
    if args.json:
        args.json.write_text(dumps(study, CONTAINMENT), encoding="utf-8")
    if args.check:
        expected = load_containment(args.check.read_text(encoding="utf-8"))
        if expected != study:
            print(f"\nthe counts differ from {args.check}", file=sys.stderr)
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
