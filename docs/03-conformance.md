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
  regular expressions and on large numbers, and drafts 07, 06 and 04 through `upgrade`.

  ```bash
  uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
  uv run python tools/suite.py --draft 7 --check docs/studies/json-schema-test-suite-draft7.json
  uv run python tools/suite.py --draft 6 --check docs/studies/json-schema-test-suite-draft6.json
  uv run python tools/suite.py --draft 4 --check docs/studies/json-schema-test-suite-draft4.json
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
| refused | `unevaluatedProperties`, `unevaluatedItems`, `$anchor`, `$dynamicRef`, `$dynamicAnchor`; an embedded `$id`, and a pointer through one; a reference outside the document |

A keyword outside the vocabularies is an annotation, as draft 2020-12 says to treat it,
and `Compiler.ignored` records it: `x-label` or OpenAPI's `nullable` assert nothing. Two
draft-07 keywords that 2020-12 removed, `additionalItems` and `dependencies`, are refused
in a 2020-12 schema rather than ignored: a schema carrying them was written to a draft
where they assert, and ignoring them would admit values its author meant to refuse. In a
draft-07 schema `upgrade` translates them.

## Differences ledger

| what | the specification | `jsonschema` 4.26.0 | valplan | why |
|---|---|---|---|---|
| `pattern` classes `\d`, `\w`, `\s`, `.`, boundaries `\b`, `\B` | ECMA-262: ASCII digits and word characters, ECMA-262 white space, any character but four line terminators, boundaries of ASCII word characters | Python's `re`: Unicode classes | ECMA-262 | the specification; on `optional/ecmascript-regex` the package passes 42 of 74, valplan 74 of 74 (`tools/suite.py --reference`) |
| `$` before a final newline | no match | match | no match | the specification |
| fractional `multipleOf` | the decimal numbers written | binary floats: `0.0075` is not a multiple of `0.0001` | exact rationals: a value's shortest decimal, an integral value its integer | the specification; an integral value read as its integer agrees with an integral step's reading, as it must, since a multiple of 3 is one of 1.5 |
| a number written with a fraction or an exponent: a bound, a constant | the decimal number written | the double `json.loads` returns | the double `json.loads` returns | the universe is what `json.loads` returns: `{"maximum": 1e23}` refuses `10**23`, since `1e23` parses to 99999999999999991611392 |
| a string holding a lone surrogate, which `json.loads` returns for `"\udc00"` | a pattern searches its code units | Python's `re` searches its code points | no pattern matches it, and a property name holding one is refused | valgebra's engine reads Unicode text, and such a string is none; RFC 8259 calls its behaviour unpredictable |
| `integer` in a draft-04 schema | a number written without a fraction or an exponent: `1.0` and `1e300` are none | the same | an integral number, as draft 2020-12 reads `integer`: `1.0` and `1e300` are integers | `upgrade` reads a draft-04 schema as the draft 2020-12 one, whose `integer` is a number's value; no 2020-12 keyword says "an int, not a float" |
| integral constants above 2**53 | one number each | one number each | one number each, its float spelling only when the float is the same number | `9007199254740993` and `9007199254740992.0` are two numbers |
| `additionalItems`, `dependencies` in a 2020-12 schema | not keywords: annotations | annotations | refused | see the inventory |

## The valgebra boundary

`valplan/_valgebra.py` is the only module that imports valgebra, and the derived forms
the compiler needs — the conditional, key presence, exactly-one-of, a keyword's scope, a
fixed-length list, the callback path — are written there once, as the recipes of
valgebra's documentation. A test fails if any other module imports valgebra.
