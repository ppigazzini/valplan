"""Run the official JSON-Schema-Test-Suite against the compiler and count the outcomes.

Each test case is a schema, an instance and the verdict the specification requires. A
schema the compiler refuses is skipped and counted with the reason; every other instance
is checked by membership in the compiled set. The counts are the record: a pass rate is
computed where it is printed.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from valplan.schema import Compiler, Unsupported


@dataclass(slots=True)
class Outcome:
    """Counts for one suite file, and the failures by name."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    opaque: int = 0
    failures: list[str] = field(default_factory=list)
    reasons: Counter[str] = field(default_factory=Counter)


def run_file(path: Path) -> Outcome:
    """Run every case of one suite file."""
    out = Outcome()
    for group in json.loads(path.read_text(encoding="utf-8")):
        compiler = Compiler(group["schema"])
        try:
            compiled = compiler.compile(group["schema"])
        except Unsupported as exc:
            out.skipped += len(group["tests"])
            out.reasons[str(exc).split(":")[0]] += len(group["tests"])
            continue
        for test in group["tests"]:
            if compiler.opaque:
                out.opaque += 1
            if compiled.is_valid(test["data"]) == test["valid"]:
                out.passed += 1
            else:
                out.failed += 1
                out.failures.append(f"{path.stem}: {group['description']} / {test['description']}")
    return out


def run(directory: Path) -> dict[str, Outcome]:
    """Run every suite file in ``directory`` and its ``optional/``, by relative stem.

    Of the optional files, the vendored ones are the two on regular expressions: draft
    2020-12 says a pattern is ECMA-262, and only those files test what that means.
    """
    files = sorted(directory.glob("*.json")) + sorted(directory.glob("optional/*.json"))
    return {p.relative_to(directory).with_suffix("").as_posix(): run_file(p) for p in files}
