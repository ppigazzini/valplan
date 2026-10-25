# Conformance

What the compiler promises against JSON Schema, how it is checked, and where a difference
is allowed to live.

## The contract

For every keyword `valplan/schema.py` accepts and every JSON value, compiled membership
gives the verdict the specification gives. A keyword it cannot translate raises
`Unsupported`; it is never skipped. A difference not in the ledger below is a defect.

## The oracles

- **The specification**, as the official JSON-Schema-Test-Suite encodes it, vendored at
  commit `89e83a740146` with its MIT licence: draft 2020-12 with the optional files on
  regular expressions and on large numbers, and draft-07 through `upgrade`.

  ```bash
  uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
  uv run python tools/suite.py --draft 7 --check docs/studies/json-schema-test-suite-draft7.json
  ```

- **The `jsonschema` package**, pinned in the development group, as a second
  implementation: `tests/test_properties.py` compares membership on 400 random schemas
  and 25 random values each, over the keywords whose meaning the two share exactly.

Where the two oracles disagree, the specification wins, and the disagreement is a ledger
entry against the package.

## The inventory

Every keyword of the draft 2020-12 vocabularies is in exactly one class, and
`tests/test_boundaries.py` fails on a keyword left out or counted twice.

| class | keywords |
|---|---|
| translated exactly | `type`, `enum`, `const`, the four bounds, an integral `multipleOf`, `minLength`, `maxLength`, `pattern`, `prefixItems`, `items`, `contains`, `minItems`, `maxItems`, `properties`, `required`, `additionalProperties`, `minProperties`, `maxProperties`, `dependentRequired`, `dependentSchemas`, `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`, `$ref` (local pointers), a root `$id` |
| translated as an opaque predicate | `patternProperties`, `propertyNames`, `uniqueItems`, `minContains`, `maxContains`, a fractional `multipleOf` |
| annotations | `title`, `description`, `default`, `examples`, `deprecated`, `readOnly`, `writeOnly`, `format`, the three `content*` keywords, `$schema`, `$vocabulary`, `$comment`, `$defs` |
| refused | `unevaluatedProperties`, `unevaluatedItems`, `$anchor`, `$dynamicRef`, `$dynamicAnchor`; an embedded `$id`; a reference outside the document |

A keyword outside the vocabularies is an annotation, as draft 2020-12 says to treat it,
and `Compiler.ignored` records it: `x-label` or OpenAPI's `nullable` assert nothing. Two
draft-07 keywords that 2020-12 removed, `additionalItems` and `dependencies`, are refused
in a 2020-12 schema rather than ignored: a schema carrying them was written to a draft
where they assert, and ignoring them would admit values its author meant to refuse. In a
draft-07 schema `upgrade` translates them.

## Differences ledger

| what | the specification | `jsonschema` 4.26.0 | valplan | why |
|---|---|---|---|---|
| `pattern` classes `\d`, `\w`, `\s`, `.` | ECMA-262: ASCII digits and word characters, ECMA-262 white space, any character but four line terminators | Python's `re`: Unicode classes | ECMA-262 | the specification; on `optional/ecmascript-regex` the package passes 42 of 74, valplan 74 of 74 (`tools/suite.py --reference`) |
| `$` before a final newline | no match | match | no match | the specification |
| fractional `multipleOf` | the decimal numbers written | binary floats: `0.0075` is not a multiple of `0.0001` | exact rationals | the specification |
| integral constants above 2**53 | one number each | one number each | one number each, its float spelling only when the float is the same number | `9007199254740993` and `9007199254740992.0` are two numbers |
| `additionalItems`, `dependencies` in a 2020-12 schema | not keywords: annotations | annotations | refused | see the inventory |

## The valgebra boundary

`valplan/_valgebra.py` is the only module that imports valgebra, and the derived forms
the compiler needs — the conditional, key presence, exactly-one-of, a keyword's scope, a
fixed-length list, the callback path — are written there once, as the recipes of
valgebra's documentation. A test fails if any other module imports valgebra.
