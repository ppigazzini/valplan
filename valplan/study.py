"""The study files: the counts the repository publishes, and the check that reads them back.

A study is written by a tool with ``--json`` and read back by the same tool with
``--check``, which reruns the measurement and requires the same counts. It is a wire
format between two versions of this code, so its shape is declared once, here, as closed
records checked by valgebra: a key the format does not name is a defect, and every
failure is reported at once with its path.
"""

import json
from typing import Annotated, Literal

from annotated_types import Ge
from typing_extensions import TypedDict
from valgebra import ValidationError, Validator, complement

NOT_BOOL = complement(bool)
type Count = Annotated[int, NOT_BOOL, Ge(0)]


class SuiteFile(TypedDict, closed=True):
    """Outcomes of one file of the JSON-Schema-Test-Suite."""

    file: str
    passed: Count
    failed: Count
    skipped: Count
    opaque: Count


class SuiteStudy(TypedDict, closed=True):
    """The compiler against the official suite, per file."""

    format: Literal[1]
    suite_commit: str
    files: list[SuiteFile]


class TaskRow(TypedDict, closed=True):
    """What the planner and the verifier did for one task."""

    task: str
    predicates: Count
    cells: Count
    inhabited: Count
    undecided: Count
    strong: bool
    calls: Count
    tests: Count
    stops: Count
    checks: Count
    proven: Count
    refuted: Count


class CaseStudy(TypedDict, closed=True):
    """A tool library and its tasks."""

    format: Literal[1]
    library: str
    tools: Count
    tasks: list[TaskRow]


class BenchRow(TypedDict, closed=True):
    """One synthetic library: its size, its abstraction, and what the planner found."""

    tools: Count
    seed: Count
    predicates: Count
    cells: Count
    inhabited: Count
    undecided: Count
    found: bool
    calls: Count
    tests: Count
    checks: Count
    proven: Count
    expanded: Count


class BenchStudy(TypedDict, closed=True):
    """Planning time-independent counts over libraries of growing size."""

    format: Literal[1]
    max_depth: Count
    rows: list[BenchRow]


class StudyError(ValueError):
    """A study file that is malformed or contradicts itself."""


SUITE = Validator(SuiteStudy)
CASE = Validator(CaseStudy)
BENCH = Validator(BenchStudy)


def _load[T](schema: Validator[T], text: str) -> T:
    try:
        return schema.load(text)
    except ValidationError as exc:
        raise StudyError(str(exc)) from exc


def load_suite(text: str) -> SuiteStudy:
    """Parse and check a suite study."""
    return _load(SUITE, text)


def load_case(text: str) -> CaseStudy:
    """Parse and check a case study, and the rules between fields of each row."""
    study = _load(CASE, text)
    for row in study["tasks"]:
        if row["inhabited"] + row["undecided"] != row["cells"]:
            msg = f"{row['task']}: inhabited + undecided != cells"
            raise StudyError(msg)
        if row["proven"] + row["refuted"] > row["checks"]:
            msg = f"{row['task']}: more verdicts than checks"
            raise StudyError(msg)
        if row["strong"] != (row["stops"] == 0):
            msg = f"{row['task']}: a strong program has no stop, and only it"
            raise StudyError(msg)
    return study


def load_bench(text: str) -> BenchStudy:
    """Parse and check a bench study."""
    study = _load(BENCH, text)
    for row in study["rows"]:
        if row["inhabited"] + row["undecided"] != row["cells"] or row["proven"] > row["checks"]:
            msg = f"bench row {row['tools']}/{row['seed']} contradicts itself"
            raise StudyError(msg)
    return study


def dumps[T](study: T, schema: Validator[T]) -> str:
    """Serialise a study, refusing one this code should never have built."""
    try:
        schema.validate(study)
    except ValidationError as exc:
        raise StudyError(str(exc)) from exc
    return json.dumps(study, indent=1) + "\n"
