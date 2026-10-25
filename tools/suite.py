"""Run the JSON-Schema-Test-Suite against the compiler; print, write or check the study.

uv run python tools/suite.py
uv run python tools/suite.py --json docs/studies/json-schema-test-suite.json
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
"""

import argparse
import sys
from pathlib import Path

from valplan.study import SUITE, SuiteFile, SuiteStudy, dumps, load_suite
from valplan.suite import run

ROOT = Path(__file__).parent.parent
SUITE_DIR = ROOT / "tests" / "data" / "json-schema-test-suite"
COMMIT = (SUITE_DIR / "COMMIT").read_text(encoding="utf-8").strip()


def measure() -> SuiteStudy:
    """Run every vendored suite file."""
    files = [
        SuiteFile(file=stem, passed=o.passed, failed=o.failed, skipped=o.skipped, opaque=o.opaque)
        for stem, o in run(SUITE_DIR).items()
    ]
    return SuiteStudy(format=1, suite_commit=COMMIT, files=files)


def table(study: SuiteStudy) -> str:
    """Render totals and the files with a skip or a failure."""
    rows = study["files"]
    passed = sum(r["passed"] for r in rows)
    failed = sum(r["failed"] for r in rows)
    skipped = sum(r["skipped"] for r in rows)
    opaque = sum(r["opaque"] for r in rows)
    lines = [
        f"JSON-Schema-Test-Suite {study['suite_commit'][:12]}, draft 2020-12, {len(rows)} files",
        "",
        (
            f"run {passed + failed}: passed {passed}, failed {failed}; "
            f"skipped {skipped} (outside the supported keywords); "
            f"{opaque} of the run cases go through an opaque predicate"
        ),
        "",
        "| file | passed | failed | skipped |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {r['file']} | {r['passed']} | {r['failed']} | {r['skipped']} |"
        for r in rows
        if r["failed"] or r["skipped"]
    ]
    return "\n".join(lines)


def reference() -> str:
    """Run the `jsonschema` package on the vendored optional files, for comparison."""
    import json  # noqa: PLC0415
    import warnings  # noqa: PLC0415
    from importlib.metadata import version  # noqa: PLC0415

    import jsonschema  # noqa: PLC0415 - a dev dependency, used by this option alone

    lines = [f"jsonschema {version('jsonschema')} on the optional files", ""]
    for path in sorted(SUITE_DIR.glob("optional/*.json")):
        passed = failed = 0
        for group in json.loads(path.read_text(encoding="utf-8")):
            validator = jsonschema.Draft202012Validator(group["schema"])
            for test in group["tests"]:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    try:
                        got = validator.is_valid(test["data"])
                    except Exception:  # noqa: BLE001 - a crash is a wrong verdict here
                        got = None
                if got == test["valid"]:
                    passed += 1
                else:
                    failed += 1
        lines.append(f"optional/{path.stem}: passed {passed}, failed {failed}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Measure, then print, write or check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--json", type=Path)
    out.add_argument("--check", type=Path)
    out.add_argument("--reference", action="store_true", help="the jsonschema package instead")
    args = parser.parse_args(argv)
    if args.reference:
        print(reference())
        return 0
    study = measure()
    print(table(study))
    if args.json:
        args.json.write_text(dumps(study, SUITE), encoding="utf-8")
    if args.check:
        expected = load_suite(args.check.read_text(encoding="utf-8"))
        if expected != study:
            print(f"\nthe suite counts differ from {args.check}", file=sys.stderr)
            return 1
        print(f"\nno difference against {args.check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
