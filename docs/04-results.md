# Results

Every number below is printed by a committed command and recorded as counts in
[`studies/`](studies/); each tool's `--check` reruns it.

## The compiler

```bash
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
uv run python tools/suite.py --draft 7 --check docs/studies/json-schema-test-suite-draft7.json
uv run python tools/suite.py --draft 6 --check docs/studies/json-schema-test-suite-draft6.json
uv run python tools/suite.py --draft 4 --check docs/studies/json-schema-test-suite-draft4.json
```

Draft 2020-12, with the four optional files on regular expressions and large numbers: 1071
of the 1071 cases run pass; 327 are skipped: the `unevaluatedItems` and
`unevaluatedProperties` files (200 cases), dynamic, anchor and remote references, and a
custom metaschema. Through `upgrade`: draft-07, 870 of the 870 cases run pass, 59
skipped; draft-06, 790 of the 790 cases run pass, 51 skipped; draft-04, 587 of the 587
cases run pass, 31 skipped. See [`02-compiler.md`](02-compiler.md#measured).

## The helpdesk library

```bash
uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
```

10 MCP tools, 4 tasks, programs searched to depth 6.

| task | cells (inhabited / undecided) | program | calls | tests | stops | proven |
|---|---|---|---:|---:|---:|---|
| ticket | 37 (37 / 0) | strong | 2 | 0 | 0 | 6 of 6 |
| settle-latest-invoice | 35 (35 / 0) | strong | 3 | 2 | 0 | 14 of 14 |
| escalate | 37 (37 / 0) | weak | 3 | 1 | 1 | 9 of 10 |
| vat-for-customer | 35 (35 / 0) | weak | 2 | 1 | 1 | 5 of 6 |

- The predicates number 26 to 27 per task, so the minterms number up to 2^27; the cells
  number 35 to 37, every one proven inhabited by a member.
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

Libraries of 8 to 256 tools from `valplan/bench.py`, 3 seeds per size, two families. In
both a planted chain ends in two finishing tools that split a value, so every strong
program tests it; the other tools are distractors over random entities.

**Strings**: identifiers are disjoint patterns and the split value an enum status.

| tools | predicates | cells | undecided | found | proven | expanded (3 seeds) |
|---:|---:|---:|---:|---|---|---|
| 8 | 12 to 14 | 17 to 18 | 0 | 3 of 3 | every check | 24, 31, 44 |
| 16 | 15 to 16 | 18 | 0 | 3 of 3 | every check | 54, 56, 61 |
| 32 | 19 to 20 | 22 | 0 | 3 of 3 | every check | 117, 128, 311 |
| 64 | 31 | 33 | 0 | 3 of 3 | every check | 51, 223, 377 |
| 128 | 52 | 54 | 0 | 3 of 3 | every check | 190, 470, 513 |
| 256 | 95 | 97 | 0 | 3 of 3 | every check | 227, 277, 848 |

**Numbers**: every tool also takes a quota (an integer range in 10000 to 20000) and
returns a measure (a range in 0 to 1000); the finishing tools split the measure at 500, and
every distractor's measure straddles 500.

| tools | predicates | cells | undecided | found | proven | expanded (3 seeds) |
|---:|---:|---:|---:|---|---|---|
| 8 | 21 to 22 | 33 to 35 | 0 | 3 of 3 | all but 2 | 24, 36, 55 |
| 16 | 38 | 65 to 67 | 0 | 3 of 3 | all but 2 | 95, 109, 125 |
| 32 | 74 | 130 to 134 | 0 | 3 of 3 | all but 2 | 170, 321, 853 |
| 64 | 148 to 149 | 262 to 268 | 0 | 3 of 3 | all but 2 | 117, 2040, 3616 |
| 128 | 297 to 298 | 514 to 519 | 0 | 3 of 3 | all but 2 | 537, 2616, 12497 |
| 256 | 597 | 960 to 984 | 0 | 3 of 3 | all but 2 | 1159, 2337, 34818 |

- Cells grow with the predicates, not with the minterms: the identifiers' patterns are
  pairwise disjoint and decided once per pair, and the numeric cells are decided by
  interval arithmetic.
- The two unproven checks of every numeric program are on its *else* branch: the measure
  narrowed to `[0, 1000]` minus `[0, 499]`, bound to an argument of `[500, 1000]`. The cells
  prove the link; valgebra answers `undecided`, because it does not decide the complement
  of an integer range whose float spelling is admitted. `tests/test_synth.py` runs four of
  these programs 20 times each against tools returning random values inside their output
  schemas: no contract is broken.
- Some programs have fewer than 4 calls: a distractor happens to shorten the chain.
- Building the abstraction dominates the run time, which `tools/bench.py` prints beside
  the counts and does not record: on the machine the study was produced on, 12 s for 256
  string tools and up to 10 minutes for 256 numeric tools, where the pairwise relations of
  597 predicates are decided one by one. The libraries run in parallel, one per core.

## Undecided cells

None, in the helpdesk library or the synthetic ones: every cell is proven empty or proven
inhabited by a member. The last to be decided is the helpdesk's integers inside
`get_subscription.seats` (at least 1) and `vat_rate.rate_percent` (0 to 30) and outside
`latest_invoice.amount_cents` (1 to 500000), next to `apply_discount.percent` (5 to 30 in
steps of 5). valgebra does not decide the complement of an integer range whose float
spelling is admitted; interval arithmetic proves the cell empty, since 1 to 30 lies inside
1 to 500000, and reads the step as a lattice (`valplan/ranges.py`).

An undecided cell would be kept and covered, so it would cost completeness, never
soundness. `tests/test_ranges.py` holds the interval rule to enumeration on 3000 random
cells of ranges and steps.

## Not measured

- Tool libraries published by real MCP servers.
- Programs proposed by a language model. The verifier reads them as JSON; a comparison
  needs a fixed model, prompt and task set, run and recorded.
