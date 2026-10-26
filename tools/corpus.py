"""Compile a corpus of real-world JSON Schemas; print, write or check the study.

    uv run python tools/corpus.py
    uv run python tools/corpus.py --json docs/studies/jsonschemabench.json
    uv run python tools/corpus.py --check docs/studies/jsonschemabench.json

The corpus is JSONSchemaBench (Geng et al., 2025; MIT): 9558 schemas from GitHub, the JSON
Schema Store, Kubernetes, Snowplow, the Washington Post and function-calling data. It is
fetched at a pinned commit into ``results/``, which is not committed, and never vendored.

Each schema is compiled and counted as compiled, refused (by reason) or crashed. For each
compiled schema, values drawn from it and the generic values the abstraction tries are
checked against it and against the `jsonschema` package's validator for its draft; a
value the two read differently is a disagreement. Two readings differ by design and are
in the ledger of ``docs/03-conformance.md``: patterns follow ECMA-262 where the package
uses Python's ``re``, and draft-04's ``integer`` is read as draft 2020-12's.
"""

import argparse
import io
import json
import os
import random
import signal
import sys
import tarfile
import urllib.request
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from valplan.abstraction import GENERIC
from valplan.sample import Sampler
from valplan.schema import Unsupported, compile_schema, older, upgrade
from valplan.study import CORPUS, CorpusStudy, CorpusSubset, Refusal, dumps, load_corpus

ROOT = Path(__file__).parent.parent
CORPUS_NAME = "guidance-ai/jsonschemabench"
COMMIT = "9a94995b9279ae3af3aed4b2629172790b968d14"
CACHE = ROOT / "results" / f"jsonschemabench-{COMMIT[:12]}"
#: Seconds one schema may take; none of the corpus needs more than one.
TIMEOUT = 60
VALIDATORS = {
    7: jsonschema.Draft7Validator,
    6: jsonschema.Draft6Validator,
    4: jsonschema.Draft4Validator,
}


def fetch(cache: Path) -> None:
    """Download the corpus at `COMMIT` and keep its schema files, one per JSON file."""
    url = f"https://codeload.github.com/{CORPUS_NAME}/tar.gz/{COMMIT}"
    with urllib.request.urlopen(url, timeout=300) as response:
        archive = response.read()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = PurePosixPath(member.name).parts
            data = len(parts) == 4 and parts[1] == "data" and parts[3].endswith(".json")  # noqa: PLR2004
            if member.isfile() and data:
                member.name = f"{parts[2]}/{parts[3]}"
                tar.extract(member, cache, filter="data")


class _OutOfTimeError(Exception):
    pass


def _alarm(*_: object) -> None:
    raise _OutOfTimeError


#: What the compiler does not read, by the start of the refusal it gives.
REASONS = (
    ("$schema", "a $schema it does not read"),
    ("keyword '$id'", "an embedded $id"),
    ("pattern ", "a pattern outside valgebra's regex dialect"),
    ("negated class", "a pattern outside valgebra's regex dialect"),
    ("$ref", "a $ref outside the document, to an anchor, or through an embedded $id"),
    ("valgebra refuses", "a set valgebra refuses to build"),
    ("property name", "a property name valgebra cannot hold"),
)


def reason(message: str) -> str:
    """Return the category of a refusal message: what the compiler does not read."""
    for start, category in REASONS:
        if message.startswith(start):
            return category
    if message.startswith("keyword '"):
        return f"the keyword {message.split(chr(39))[1]}"
    return message.partition(":")[0][:60]


def one(path: Path) -> tuple[str, str, str, int, int]:
    """Measure one schema: its outcome, refusal reason, values checked and disagreements."""
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT)
    subset = path.parent.name
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        try:
            compiled = compile_schema(schema)
        except Unsupported as exc:
            return subset, "refused", reason(str(exc)), 0, 0
        draft = older(schema)
        root = upgrade(schema, draft) if draft is not None else schema
        drawn = Sampler(root, random.Random(path.name)).draw(root, 20)
        reference = VALIDATORS.get(draft or 0, jsonschema.Draft202012Validator)(schema)
        values = [*drawn, *GENERIC]
        disagreed = sum(compiled.is_valid(v) != reference.is_valid(v) for v in values)
        return subset, "compiled", "", len(values), disagreed
    except _OutOfTimeError:
        return subset, "timed_out", "", 0, 0
    except Exception as exc:  # noqa: BLE001 - one schema must not stop the corpus
        return subset, "crashed", f"{type(exc).__name__}: {exc}"[:120], 0, 0
    finally:
        signal.alarm(0)


def measure(cache: Path, jobs: int) -> CorpusStudy:
    """Measure every schema of the corpus, ``jobs`` at a time."""
    files = sorted(cache.glob("*/*.json"))
    counts: dict[str, Counter[str]] = {}
    refusals: Counter[str] = Counter()
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for subset, outcome, why, values, disagreed in pool.map(one, files, chunksize=8):
            count = counts.setdefault(subset, Counter())
            count.update({"schemas": 1, outcome: 1, "values": values, "disagreed": disagreed})
            if outcome == "refused":
                refusals[why] += 1
            if outcome == "crashed":
                print(f"crashed in {subset}: {why}", file=sys.stderr)
    rows = [
        CorpusSubset(
            subset=subset,
            schemas=c["schemas"],
            compiled=c["compiled"],
            refused=c["refused"],
            crashed=c["crashed"],
            timed_out=c["timed_out"],
            values=c["values"],
            disagreed=c["disagreed"],
        )
        for subset, c in sorted(counts.items())
    ]
    return CorpusStudy(
        format=1,
        corpus=CORPUS_NAME,
        commit=COMMIT,
        subsets=rows,
        refusals=[Refusal(reason=r, schemas=n) for r, n in sorted(refusals.items())],
    )


def table(study: CorpusStudy) -> str:
    """Render one row per subset, the totals, and the refusals by reason."""
    keys = ("schemas", "compiled", "refused", "crashed", "timed_out", "values", "disagreed")
    lines = [
        f"{study['corpus']} at {study['commit'][:12]}",
        "",
        "| subset | " + " | ".join(k.replace("_", " ") for k in keys) + " |",
        "|---|" + "---:|" * len(keys),
    ]
    rows: list[Any] = study["subsets"]
    lines += [f"| {r['subset']} | " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows]
    totals = {k: sum(r[k] for r in rows) for k in keys}
    lines.append("| all | " + " | ".join(str(totals[k]) for k in keys) + " |")
    lines += ["", "| refused for | schemas |", "|---|---:|"]
    lines += [f"| {r['reason']} | {r['schemas']} |" for r in study["refusals"]]
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
    if not any(CACHE.glob("*/*.json")):
        fetch(CACHE)
    study = measure(CACHE, args.jobs)
    print(table(study))
    if args.json:
        args.json.write_text(dumps(study, CORPUS), encoding="utf-8")
    if args.check:
        expected = load_corpus(args.check.read_text(encoding="utf-8"))
        if expected != study:
            print(f"\nthe counts differ from {args.check}", file=sys.stderr)
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
