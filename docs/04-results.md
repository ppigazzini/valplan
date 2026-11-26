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
| ticket | 37 (37 / 0) | strong | 2 | 0 | 0 | 4 of 4 |
| settle-latest-invoice | 35 (35 / 0) | strong | 3 | 2 | 0 | 10 of 10 |
| escalate | 37 (37 / 0) | weak | 3 | 1 | 1 | 6 of 7 |
| vat-for-customer | 35 (35 / 0) | weak | 2 | 1 | 1 | 3 of 4 |

- The predicates number 26 to 27 per task, so the minterms number up to 2^27; the cells
  number 35 to 37, every one proven inhabited by a member.
- Both strong programs verify in full under valgebra-planning's verifier. Each weak program's
  one unproven check is its stop. `escalate` stops on `c1.tier in {'pro', 'free'}`, the
  complete list, since `tier` is an enum; `vat-for-customer` stops on countries outside
  the six `vat_rate` lists, shown by example, since a country is a pattern.
- The hand-written chain in `examples/helpdesk/naive-escalate.json`, which escalates every
  customer, is refuted at one binding, `c1.tier <= escalate.tier`, `not_subset` with the value
  `'free'`. `escalate`'s input constrains each argument alone, so its argument record holds
  once each argument does, and no link asks it apart.
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
together, as valgebra-planning's planner cuts them (its `predicates` and `abstract`), the 37
predicates give 60 cells, of which 23 are undecided, 22 of them array cells valgebra does not
part. They are kept, so no wrong program is admitted, and they cost the search. The cut asks
valgebra 507 relations.

The count reads the stored listings, with no network, so it is in the gate. A pinned server is
not a pinned listing: its dependencies resolve when it starts and its SDK writes the schemas, so
`tools/census.py --refresh --check docs/studies/census.json` reads the servers again and reports
a listing that moved. A moved listing, or a new release of a server, is a new study.

## Two planners

```bash
uv run --no-sync python tools/planners.py --check docs/studies/planners.json
```

valplan's planner and valgebra-planning's run on the same tasks, both to depth 6 and the first
16 bindings of a call, over contracts valgebra-planning's reader reads, and valgebra-planning's
verifier judges every program either finds. Every link of every program found is proven.

| tasks | valplan | valgebra-planning | cells, valplan | cells, valgebra-planning | states expanded, valplan | states expanded, valgebra-planning |
|---|---|---|---|---|---|---|
| helpdesk, 4 | 2 strong, 2 weak | 2 strong, 2 weak | 35 to 37 | 19 to 37 | 9 to 3079 | 3 to 1148 |
| parcels, the 4 with no rule | 2 strong, 1 weak, 1 none | 2 strong, 2 weak | 26 | 11 to 18 | 7 to 1186 | 3 to 30 |
| valplan's strings, 8 to 128 tools, 9 | 9 strong | 9 strong | 17 to 54 | 15 to 54 | 24 to 548 | 16 to 161 |
| valplan's numbers, 8 to 128 tools, 9 | 9 strong | 9 strong | 33 to 519 | 24 to 507 | 24 to 12497 | 16 to 1796 |
| valgebra-planning's chain, 8 to 128 tools, 9 | 9 strong | 9 strong | 18 to 198 | 12 | 62 to 2638952 | 10 |

- **Coverage agrees on 34 of 35 tasks.** On the parcels' "return a parcel" valgebra-planning
  finds a weak program and valplan none: booking a return takes a state and a weight that each
  only overlap the argument, and a guarded call here tests one argument, its others held
  whole ([01-method.md](01-method.md#limits), search bounds).
- **The cost is where the cut is.** valgebra-planning drops first every tool the goal cannot be
  reached through, so on its own chain family its cut stays at 12 cells and its search at 10
  states at every size, where valplan's cut grows with the distractors and its search reaches
  2638952 states at 128 tools.
- **Each family was written by one planner's author**, so a comparison holds on these sets
  alone. A failure to find a strong program is the search's under the bounds and certifies
  nothing; a found program is proven link by link.

Over the census's 66 tools, for a task taking a string to a string, each planner's own cut:
valgebra-planning's 37 predicates give 60 cells, 23 undecided, as the census reads them;
valplan's 38 give 64 cells, 28 undecided. The two cut different predicates, so the counts are
each cut's, not a measure of one rule.

## Cell rules on one cut

```bash
uv run --no-sync python tools/rules.py --check docs/studies/rules.json
```

The predicates valgebra-planning's planner cuts for a task, sorted by their names, cut by
valgebra-planning's `abstract` and by valplan's abstraction bare, with each of its three rules
alone, and with all three. Every valplan cut gets one pool of members, drawn from each
predicate's schema by a stream seeded by its names; `cells` counts what a cut cannot prove empty,
`undecided` those with no member found.

| task | predicates | valgebra-planning | valplan bare | listed values | intervals | union branches | all three |
|---|---:|---|---|---|---|---|---|
| census | 37 | 63 (26) | 63 (28) | 63 (28) | 63 (28) | 63 (28) | 63 (28) |
| numbers, 32 tools | 74 | 130 (0) | 130 (10) | 130 (10) | 130 (0) | 130 (10) | 130 (0) |
| numbers, 64 tools | 147 | 260 (0) | 260 (32) | 260 (32) | 260 (0) | 260 (32) | 260 (0) |

- **The interval rule is the one that decides here**, and it decides for valplan's own cut:
  bare, valplan keeps valgebra-planning's 130 and 260 cells with 10 and 32 of them undecided,
  and at 128 tools runs past 150 s; with the rule none is undecided, as in valgebra-planning's
  cut, which reaches them with no interval rule. valgebra 0.0.34 proves eight of the bare
  64-tool cut's cells empty, and valgebra-jsonschema 0.0.7, reading a schema's bounds as one
  interval a kind, two more.
- **Listed values and union branches decide nothing on these tasks**: each leaves the bare cut's
  counts as they are.
- **On the census the two cuts part by two cells**: each keeps 63, valgebra-planning's 26
  undecided and valplan's bare cut 28. valgebra 0.0.31 decides two of valgebra-planning's array
  cells and none of valplan's, valgebra 0.0.34 proves sixteen cells of each cut empty, and none
  of the three rules moves valplan's count.

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
