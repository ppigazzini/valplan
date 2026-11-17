# Results

Every number below is printed by a committed command and recorded as counts in
[`studies/`](studies/); each tool's `--check` reruns it.

The compiler's counts are the
[companion's](https://github.com/ppigazzini/valgebra-jsonschema/blob/main/docs/04-results.md).

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
  customer, is refuted at one binding, `c1.tier <= escalate.tier`, and at the argument
  record that carries it, `arguments <= escalate input`; both are `not_subset`.
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
| 8 | 12 to 14 | 17 to 18 | 0 | 3 of 3 | every check | 24, 33, 47 |
| 16 | 15 to 16 | 18 | 0 | 3 of 3 | every check | 54, 59, 64 |
| 32 | 19 to 20 | 22 | 0 | 3 of 3 | every check | 117, 138, 343 |
| 64 | 31 | 33 | 0 | 3 of 3 | every check | 51, 235, 389 |
| 128 | 52 | 54 | 0 | 3 of 3 | every check | 205, 488, 548 |
| 256 | 95 | 97 | 0 | 3 of 3 | every check | 243, 290, 929 |

**Numbers**: every tool also takes a quota (an integer range in 10000 to 20000) and
returns a measure (a range in 0 to 1000); the finishing tools split the measure at 500, and
every distractor's measure straddles 500.

| tools | predicates | cells | undecided | found | proven | expanded (3 seeds) |
|---:|---:|---:|---:|---|---|---|
| 8 | 21 to 22 | 33 to 35 | 0 | 3 of 3 | every check | 24, 36, 55 |
| 16 | 38 | 65 to 67 | 0 | 3 of 3 | every check | 95, 109, 125 |
| 32 | 74 | 130 to 134 | 0 | 3 of 3 | every check | 170, 321, 853 |
| 64 | 148 to 149 | 262 to 268 | 0 | 3 of 3 | every check | 117, 2040, 3616 |
| 128 | 297 to 298 | 514 to 519 | 0 | 3 of 3 | every check | 537, 2616, 12497 |
| 256 | 597 | 960 to 984 | 0 | 3 of 3 | every check | 1159, 2337, 34818 |

- Cells grow with the predicates, not with the minterms: the identifiers' patterns are
  pairwise disjoint and decided once per pair, and the numeric cells are decided by
  interval arithmetic.
- Every check of a numeric program is proven, its *else* branch's too: the measure narrowed
  to `[0, 1000]` minus `[0, 499]`, bound to an argument of `[500, 1000]`, is a complement of an
  integer range whose float spelling is admitted, which valgebra decides. `tests/test_synth.py`
  runs four of these programs 20 times each against tools returning random values inside their
  output schemas: no contract is broken.
- Some programs have fewer than 4 calls: a distractor happens to shorten the chain.
- Building the abstraction dominates the run time, which `tools/bench.py` prints beside
  the counts and does not record: on the machine the study was produced on, 3 s for 256
  string tools and 87 to 98 s for 256 numeric tools, where the pairwise relations of
  597 predicates are decided one by one. The libraries run in parallel, one per core.

## Real servers

```bash
uv run --no-sync python tools/census.py --check docs/studies/census.json
```

The seven official MCP reference servers, each pinned to one release (`SERVERS` in
`tools/census.py`), list 66 tools, stored as listed under `examples/census/` beside the license
they carry. valgebra-planning's contract reader reads every one through valgebra-jsonschema,
and 31 carry an `outputSchema`, which is 12 distinct schemas, all 16 of filesystem's being one
text wrapper. Of the 126 arguments, 72 carry a bare type and nothing more. Cut into cells
together, as valgebra-planning's planner cuts them (its `predicates` and `abstract`), the 106
predicates give 127 cells, of which 92 are undecided, 91 of them array cells: arrays of records
met with the complements of other arrays of records, 63 of them with arrays of strings too,
which valgebra does not part. They are kept, so no wrong program is admitted, and they cost the
search. The cut asks valgebra 3,082 relations.

The count reads the stored listings, with no network, so it is in the gate. A pinned server is
not a pinned listing: its dependencies resolve when it starts and its SDK writes the schemas, so
`tools/census.py --refresh --check docs/studies/census.json` reads the servers again and reports
a listing that moved. A moved listing, or a new release of a server, is a new study.

## Undecided cells

None, in the helpdesk library or the synthetic ones: every cell is proven empty or proven
inhabited by a member. The last to be decided is the helpdesk's integers inside
`get_subscription.seats` (at least 1) and `vat_rate.rate_percent` (0 to 30) and outside
`latest_invoice.amount_cents` (1 to 500000), next to `apply_discount.percent` (5 to 30 in
steps of 5). Interval arithmetic proves the cell empty, since 1 to 30 lies inside 1 to 500000,
and reads the step as a lattice (`valplan/ranges.py`). valgebra decides such cells too, up to 112
ranges, and the rule is what keeps them cheap: on 64 numeric tools the rule's 262 cells, 3616
expanded and 1.9 s are 297 cells, 59 of them undecided, 16234 expanded and 5.0 s without it.

An undecided cell would be kept and covered, so it would cost completeness, never
soundness. `tests/test_ranges.py` holds the interval rule to enumeration on 3000 random
cells of ranges and steps.

## Not measured

- Programs proposed by a language model. The verifier reads them as JSON; a comparison
  needs a fixed model, prompt and task set, run and recorded.
