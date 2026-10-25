# Results

Every number below is printed by a committed command and recorded as counts in
[`studies/`](studies/); each tool's `--check` reruns it.

## The compiler

```bash
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
```

1061 of the 1061 cases run pass, the two optional files on regular expressions included;
327 are skipped: the `unevaluatedItems` and `unevaluatedProperties` files (200 cases),
dynamic, anchor and remote references, and a custom metaschema. See
[`02-compiler.md`](02-compiler.md#measured).

## The helpdesk library

```bash
uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
```

10 MCP tools, 4 tasks, programs searched to depth 6.

| task | cells (inhabited / undecided) | program | calls | tests | stops | proven |
|---|---|---|---:|---:|---:|---|
| ticket | 38 (35 / 3) | strong | 2 | 0 | 0 | 6 of 6 |
| settle-latest-invoice | 36 (34 / 2) | strong | 3 | 2 | 0 | 14 of 14 |
| escalate | 38 (35 / 3) | weak | 3 | 1 | 1 | 9 of 10 |
| vat-for-customer | 36 (34 / 2) | weak | 2 | 1 | 1 | 5 of 6 |

- The predicates number 27 to 28 per task, so the minterms number up to 2^28; the cells
  number 36 to 38.
- Both strong programs verify in full under the independent verifier. Each weak program's
  one unproven check is its stop. `escalate` stops on `c1.tier in {'pro', 'free'}`, the
  complete list, since `tier` is an enum; `vat-for-customer` stops on countries outside
  the six `vat_rate` lists, shown by example, since a country is a pattern.
- The hand-written chain in `examples/helpdesk/naive-escalate.json`, which escalates every
  customer, is refuted at one binding: `c1.tier <= escalate.tier`, `not_subset`.
- `tests/test_synth.py` runs the strong `settle-latest-invoice` program 25 times against
  mock tools that return random values valid for their output schemas: no contract is
  broken and every answer lies in the goal.

## Synthetic libraries

```bash
uv run python tools/bench.py --check docs/studies/bench.json
```

Libraries of 8 to 256 tools from `valplan/bench.py`: a planted chain of three calls ends
in two finishing tools that split an enum status, so every strong program tests it; the
other tools are distractors over random entities, some requiring a narrower status.

| tools | predicates | cells | undecided | found | proven | expanded (3 seeds) |
|---:|---:|---:|---:|---|---|---|
| 8 | 12 to 14 | 17 to 18 | 0 | 3 of 3 | every check | 24, 31, 44 |
| 16 | 15 to 16 | 18 | 0 | 3 of 3 | every check | 54, 56, 61 |
| 32 | 19 to 20 | 22 | 0 | 3 of 3 | every check | 117, 128, 311 |
| 64 | 31 | 33 | 0 | 3 of 3 | every check | 51, 223, 377 |
| 128 | 52 | 54 | 0 | 3 of 3 | every check | 190, 470, 513 |
| 256 | 95 | 97 | 0 | 3 of 3 | every check | 227, 277, 848 |

- Cells grow with the predicates, not with the minterms: 97 cells at 95 predicates. The
  identifiers' patterns are pairwise disjoint, and each pair is decided once.
- Two of the 18 programs have 3 calls, not 4: a distractor happens to shorten the chain.
- The search expands at most 848 states. Building the abstraction dominates the run time,
  which `tools/bench.py` prints beside the counts and does not record.

## Undecided cells

2 or 3 cells per helpdesk task stay undecided, none in the synthetic libraries. They are the ones valgebra can prove neither empty
nor inhabited and no drawn value falls in — for example a string cell carved out by the
complements of several patterns. They are kept, so they cost completeness, never soundness.
Each is a concrete question for valgebra's decided fragment: the emptiness of a meet of a
pattern with the complements of a union of patterns and literals.

## Not measured

- Tool libraries published by real MCP servers.
- Programs proposed by a language model. The verifier reads them as JSON; a comparison
  needs a fixed model, prompt and task set, run and recorded.
