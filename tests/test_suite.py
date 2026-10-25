from pathlib import Path

import pytest

from valplan.suite import run

SUITE = Path(__file__).parent / "data" / "json-schema-test-suite"


@pytest.fixture(scope="module")
def outcomes():
    return run(SUITE)


def test_every_case_the_compiler_accepts_gets_the_specified_verdict(outcomes):
    failures = [f for o in outcomes.values() for f in o.failures]
    assert failures == []


def test_the_compiler_accepts_the_core_assertion_vocabulary(outcomes):
    for stem in (
        "type",
        "enum",
        "const",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "contains",
        "properties",
        "required",
        "additionalProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if-then-else",
        "dependentRequired",
        "boolean_schema",
    ):
        # A few cases in these files combine the keyword with `unevaluated*`, which is out
        # of scope; nothing else may be skipped.
        assert all("unevaluated" in r for r in outcomes[stem].reasons), stem


def test_a_skip_names_its_reason(outcomes):
    for o in outcomes.values():
        assert sum(o.reasons.values()) == o.skipped
