"""The package's boundaries, held by tests rather than by convention."""

import ast
import json
from pathlib import Path

from valplan.schema import ANNOTATIONS, REFUSED, SUPPORTED

PACKAGE = Path(__file__).parent.parent / "valplan"

#: Every keyword of the draft 2020-12 vocabularies, from the meta-schemas.
DRAFT_2020_12 = {
    "core": [
        "$id",
        "$schema",
        "$ref",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "$comment",
        "$defs",
    ],
    "applicator": [
        "prefixItems",
        "items",
        "contains",
        "additionalProperties",
        "properties",
        "patternProperties",
        "dependentSchemas",
        "propertyNames",
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
    ],
    "unevaluated": ["unevaluatedItems", "unevaluatedProperties"],
    "validation": [
        "type",
        "const",
        "enum",
        "multipleOf",
        "maximum",
        "exclusiveMaximum",
        "minimum",
        "exclusiveMinimum",
        "maxLength",
        "minLength",
        "pattern",
        "maxItems",
        "minItems",
        "uniqueItems",
        "maxContains",
        "minContains",
        "maxProperties",
        "minProperties",
        "required",
        "dependentRequired",
    ],
    "meta-data": [
        "title",
        "description",
        "default",
        "deprecated",
        "readOnly",
        "writeOnly",
        "examples",
    ],
    "format-annotation": ["format"],
    "content": ["contentEncoding", "contentMediaType", "contentSchema"],
}


def test_only_the_boundary_module_imports_valgebra():
    for path in PACKAGE.glob("*.py"):
        if path.name == "_valgebra.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "valgebra" not in imported, path.name


def test_every_draft_2020_12_keyword_is_classified_once():
    every = [k for words in DRAFT_2020_12.values() for k in words]
    classes = {"supported": SUPPORTED, "annotation": ANNOTATIONS, "refused": REFUSED}
    for keyword in every:
        homes = [name for name, words in classes.items() if keyword in words]
        assert len(homes) == 1, (keyword, homes)


def test_the_inventory_names_no_keyword_outside_the_vocabularies():
    every = {k for words in DRAFT_2020_12.values() for k in words}
    extra = (
        (SUPPORTED | REFUSED)
        - every
        - {"additionalItems", "dependencies", "$recursiveRef", "$recursiveAnchor", "definitions"}
    )
    assert extra == set()
    assert json.dumps(sorted(SUPPORTED))
