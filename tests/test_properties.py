"""Properties checked over many random cases rather than a few chosen ones."""

import itertools
import random

import jsonschema
import pytest
from valgebra import intersection

from valplan.bench import library
from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.schema import compile_schema
from valplan.synth import witnesses

SCALARS = [None, True, False, 0, 1, -1, 1.0, 2.5, -7, 10**6, "", "a", "ab", "abc", "Z9"]


def _value(rng, depth=2):
    kind = rng.randrange(7 if depth > 0 else 5)
    if kind < 5:
        return rng.choice(SCALARS)
    if kind == 5:
        return [_value(rng, depth - 1) for _ in range(rng.randrange(4))]
    keys = rng.sample(["a", "b", "c", "d"], rng.randrange(4))
    return {k: _value(rng, depth - 1) for k in keys}


def _schema(rng, depth=2):
    """Draw a schema over the keywords whose meaning `jsonschema` shares exactly.

    Patterns are left out (`jsonschema` reads them with Python's `re`, not ECMA-262) and
    so is a fractional `multipleOf` (it divides binary floats).
    """
    leaf = [
        lambda: {
            "type": rng.choice(
                ["null", "boolean", "integer", "number", "string", "array", "object"]
            )
        },
        lambda: {"type": rng.sample(["null", "integer", "string", "array"], 2)},
        lambda: {"enum": rng.sample(SCALARS, 3)},
        lambda: {"const": rng.choice(SCALARS)},
        lambda: {"minimum": rng.randrange(-3, 4)},
        lambda: {"exclusiveMaximum": rng.randrange(-3, 4)},
        lambda: {"multipleOf": rng.choice([1, 2, 3])},
        lambda: {"minLength": rng.randrange(3)},
        lambda: {"maxLength": rng.randrange(3)},
        lambda: {"minItems": rng.randrange(3)},
        lambda: {"maxProperties": rng.randrange(3)},
        lambda: {"required": rng.sample(["a", "b", "c"], rng.randrange(1, 3))},
    ]
    if depth == 0:
        return rng.choice(leaf)()
    nested = [
        lambda: {"items": _schema(rng, depth - 1)},
        lambda: {"prefixItems": [_schema(rng, depth - 1)], "items": _schema(rng, depth - 1)},
        lambda: {"contains": _schema(rng, depth - 1)},
        lambda: {
            "properties": {"a": _schema(rng, depth - 1), "b": _schema(rng, depth - 1)},
            "additionalProperties": rng.choice([True, False, _schema(rng, depth - 1)]),
        },
        lambda: {"anyOf": [_schema(rng, depth - 1), _schema(rng, depth - 1)]},
        lambda: {"allOf": [_schema(rng, depth - 1), _schema(rng, depth - 1)]},
        lambda: {"oneOf": [_schema(rng, depth - 1), _schema(rng, depth - 1)]},
        lambda: {"not": _schema(rng, depth - 1)},
        lambda: {"if": _schema(rng, depth - 1), "then": _schema(rng, depth - 1)},
        lambda: {"dependentRequired": {"a": ["b"]}},
    ]
    return rng.choice(leaf + nested)()


@pytest.mark.parametrize("seed", range(10))
def test_membership_agrees_with_the_jsonschema_package_on_random_schemas(seed):
    rng = random.Random(f"diff:{seed}")
    for _ in range(40):
        schema = _schema(rng)
        compiled = compile_schema(schema)
        reference = jsonschema.Draft202012Validator(schema)
        for _ in range(25):
            value = _value(rng)
            assert compiled.is_valid(value) == reference.is_valid(value), (schema, value)


@pytest.mark.parametrize("n", [8, 32])
def test_every_inclusion_and_emptiness_valgebra_proves_holds_on_every_drawn_value(n):
    lib_json, spec = library(n, 0)
    lib, task = read_tools(lib_json), read_task(spec)
    values = witnesses(lib, task)
    preds = list({s.schema: None for t in lib for s in t.args + t.results})
    for a, b in itertools.combinations(preds, 2):
        if a.is_subtype_of(b):
            assert not [v for v in values if a.is_valid(v) and not b.is_valid(v)]
        if intersection(a, b).is_empty():
            assert not [v for v in values if a.is_valid(v) and b.is_valid(v)]


def test_the_helpdesk_decisions_hold_on_every_drawn_value(library, tasks):
    values = witnesses(library, tasks["ticket"])
    preds = list({s.schema: None for t in library for s in t.args + t.results})
    for a, b in itertools.combinations(preds, 2):
        if a.is_subtype_of(b):
            assert not [v for v in values if a.is_valid(v) and not b.is_valid(v)]
        if intersection(a, b).is_empty():
            assert not [v for v in values if a.is_valid(v) and b.is_valid(v)]
