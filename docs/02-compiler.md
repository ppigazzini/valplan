# The compiler

`valplan/schema.py` compiles JSON Schema draft 2020-12 into valgebra sets. The universe is
what `json.loads` returns — `None`, `bool`, `int`, `float`, `str`, `list`, and `dict` with
`str` keys, nested. On it the translation is exact for every keyword it accepts, with
patterns read as ECMA-262 defines them; where a pattern uses a construct valgebra's engine
refuses, the schema is refused.

## Keyword semantics

An assertion keyword constrains one kind and passes every other kind: `{"minimum": 3}`
admits `"a"`. Each such keyword compiles to `complement(kind) | refined`, and a schema
object to the meet of its keywords. Where `type` already confines the instance to the
keyword's kind, the guard's other half is empty after the meet and is left out.

| keyword | set |
|---|---|
| `type` | union of kinds; `integer` is an `int` that is not a `bool`, or a `float` that is a multiple of 1 |
| `enum`, `const` | union of the constants under JSON equality: `1` and `1.0` are one number, `true` is not `1`; arrays and objects compare structurally |
| `minimum`, `maximum`, `exclusive*` | bound refinements on `int` and `float` |
| `multipleOf` | an integral step is valgebra's `MultipleOf`; a fractional step is opaque, checked in `decimal` arithmetic |
| `minLength`, `maxLength` | length refinements, in code points |
| `pattern` | `p` becomes `(?s:.*)(?:p')(?s:.*)`, where `p'` rewrites `\d`, `\w`, `\s`, their negations, `.` and `\cX` to the classes ECMA-262 gives them: ECMA-262 searches, valgebra's `Regex` matches the whole string, and the two dialects read those classes differently |
| `prefixItems`, `items` | the union of the shorter fixed prefixes and the prefix followed by a repeated tail |
| `minItems`, `maxItems`, `min/maxProperties` | length refinements |
| `contains` | arrays not all of whose elements lie outside the subschema |
| `properties`, `required`, `additionalProperties` | one record: optional and required fields, and a catch-all clause for every other key; a required key outside `properties` takes the additional schema |
| `dependentRequired`, `dependentSchemas` | "key absent, or the dependency holds" |
| `allOf`, `anyOf`, `not` | meet, union, complement within the JSON values |
| `oneOf` | each branch minus all the others |
| `if`, `then`, `else` | `(if & then) | (~if & else)` |
| `$ref` | a local JSON pointer, compiled as a `recursive` fixpoint over its target |

Annotations assert nothing and are skipped: `title`, `description`, `default`, `examples`,
`deprecated`, `readOnly`, `writeOnly`, `format` (the format-annotation vocabulary is the
default), the `content*` keywords, `$comment`, `$defs`. A root `$id` is skipped.

## Opaque keywords

Five keywords have no counterpart in valgebra's set language, so they compile to
predicates: membership is exact, and a relation that has to look inside one answers
"undecided", never a wrong proof. `Compiler.opaque` lists those a schema used.

| keyword | why |
|---|---|
| `patternProperties` | a valgebra map key is a key type or a literal, not a pattern-narrowed string |
| `propertyNames` | the same |
| `uniqueItems` | needs equality across elements |
| `minContains`, `maxContains` | need counting |
| `multipleOf` with a fractional step | `0.0075 % 0.0001` is not zero in binary floating point |

## Refused

`Unsupported` names the keyword: `unevaluatedProperties`, `unevaluatedItems`,
`$dynamicRef`, `$dynamicAnchor`, `$anchor` references, references outside the document, an
embedded `$id`, any other draft, and a property name ending in `?` (valgebra reads that
suffix as "optional"). A compiler that skipped an assertion it did not understand would
admit values the schema refuses.

## Measured

```bash
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
```

The official JSON-Schema-Test-Suite, draft 2020-12 at commit `89e83a740146`, vendored in
`tests/data/json-schema-test-suite/` with the two optional files on regular expressions:
1061 cases run, 1061 passed, 0 failed; 327 skipped by the refusals above; 175 of the run
cases go through an opaque predicate.

```bash
uv run python tools/suite.py --reference
```

On the same optional files the `jsonschema` package 4.26.0 passes 42 of the 74
`ecmascript-regex` cases and 12 of the 12 `non-bmp-regex` cases: it reads patterns with
Python's `re`, where `\d` matches any Unicode digit and `$` matches before a final newline.
