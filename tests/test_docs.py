"""The pages quote the counts the study files hold, so a regenerated study fails a stale page."""

import importlib.util
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _page(name):
    """Return a page with every run of whitespace one space: wrapping is not content."""
    return " ".join((ROOT / name).read_text(encoding="utf-8").split())


def _study(name):
    return json.loads((ROOT / "docs" / "studies" / name).read_text(encoding="utf-8"))


def _span(values):
    low, high = min(values), max(values)
    return f"{low}" if low == high else f"{low} to {high}"


def _case_tool():
    spec = importlib.util.spec_from_file_location("case", ROOT / "tools" / "case.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _suite(name):
    files = _study(name)["files"]
    return {k: sum(f[k] for f in files) for k in ("passed", "failed", "skipped", "opaque")}


class TestCompiler:
    def test_the_pages_quote_the_draft_2020_12_totals(self):
        t = _suite("json-schema-test-suite.json")
        run = t["passed"] + t["failed"]
        assert f"{t['passed']} of the {run} cases it runs" in _page("README.md")
        assert f"{t['passed']} of the {run} cases run pass" in _page("docs/04-results.md")
        assert (
            f"{run} cases run, {t['passed']} passed, {t['failed']} failed; {t['skipped']} skipped"
        ) in _page("docs/02-compiler.md")
        assert f"{t['opaque']} of the run cases" in _page("docs/02-compiler.md")

    def test_the_pages_quote_the_draft_07_totals(self):
        t = _suite("json-schema-test-suite-draft7.json")
        run = t["passed"] + t["failed"]
        assert f"draft-07, {t['passed']} of {run}" in _page("README.md")
        assert f"{t['passed']} of the {run} cases run pass" in _page("docs/04-results.md")
        assert (
            f"{run} cases run, {t['passed']} passed, {t['failed']} failed; {t['skipped']} skipped"
        ) in _page("docs/02-compiler.md")


class TestHelpdesk:
    def test_the_results_page_carries_every_task_row(self):
        study = _study("helpdesk.json")
        rows = _case_tool().table(study).splitlines()[2:]
        page = _page("docs/04-results.md")
        missing = [row for row in rows if row not in page]
        assert missing == []

    def test_the_spans_quoted_are_the_studys(self):
        tasks = _study("helpdesk.json")["tasks"]
        cells = _span([t["cells"] for t in tasks])
        predicates = _span([t["predicates"] for t in tasks])
        undecided = {t["undecided"] for t in tasks}
        page, readme = _page("docs/04-results.md"), _page("README.md")
        assert f"The predicates number {predicates} per task" in page
        assert f"the cells number {cells}" in page
        assert f"{cells} cells per task" in readme
        quoted = "none of them" if undecided == {0} else f"{_span(sorted(undecided))} of them"
        assert f"{quoted} undecided" in readme


class TestBenchmark:
    def test_the_results_page_carries_every_size_of_both_families(self):
        rows = _study("bench.json")["rows"]
        page = _page("docs/04-results.md")
        missing = []
        ordered = sorted(rows, key=lambda r: (r["family"], r["tools"]))
        for _, group in itertools.groupby(ordered, key=lambda r: (r["family"], r["tools"])):
            g = list(group)
            unproven = sorted({r["checks"] - r["proven"] for r in g})
            proven = "every check" if unproven == [0] else f"all but {_span(unproven)}"
            expanded = ", ".join(str(r["expanded"]) for r in sorted(g, key=lambda r: r["expanded"]))
            row = (
                f"| {g[0]['tools']} | {_span([r['predicates'] for r in g])} "
                f"| {_span([r['cells'] for r in g])} | {_span([r['undecided'] for r in g])} "
                f"| {sum(r['found'] for r in g)} of {len(g)} | {proven} | {expanded} |"
            )
            if row not in page:
                missing.append(row)
        assert missing == []
