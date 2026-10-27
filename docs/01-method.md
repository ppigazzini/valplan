# Method

## Contracts as typed slots

An agent does not pass one tool's result to the next whole; it fills each argument from a
value it holds. A tool is read from its MCP JSON Schema, or from a Python function's
annotations (`valplan/native.py`); both give the same slots. `valplan/contracts.py` reads
each tool as slots: one per argument, one per result field the output schema requires,
nested required fields included by their path to three levels, or one for a whole result
that is no object. Each slot's set is its property's subschema,
compiled by `valplan/schema.py`. A constraint the whole input object carries is kept: a
binding is accepted only if the assembled argument record is proven inside the tool's
whole input schema.

## The abstraction

Every slot schema, task input and goal is a predicate on JSON values. Their minterms —
each predicate taken positively or negatively — partition the JSON values into cells, and
each predicate is exactly a union of cells (`valplan/abstraction.py`). Inclusion between
the cells of two predicates implies inclusion between the predicates; the converse fails
only through an undecided cell inside one and outside the other. Narrowing a value by a
static type test is set difference. This is predicate abstraction (Graf and Saidi 1997) over a
Boolean algebra of semantic types (Frisch, Castagna and Benzaken 2008).

Building the cells is where the decision procedure works, and three rules keep it exact
and small:

- **Kinds first.** The JSON values split into seven disjoint kinds — null, boolean,
  integer, fraction, string, array, object — and a predicate splits only the cells of the
  kinds it meets. A string pattern leaves an integer cell untouched, with no complement
  term added to it.
- **Pairwise proofs settle most splits.** A cell inside a predicate disjoint from the new
  one is outside it; a cell inside a predicate below it is inside it; a cell outside a
  predicate above it is outside it. Each pair is decided once. A complement implied by a
  positive member is left out of the cell's set. Only a split no pair settles asks
  valgebra about the cell's whole set.
- **Listed values decide finite cells.** Inside an `enum`, `const`, boolean or null
  predicate of scalars a cell holds exactly the listed values that meet the rest of its
  predicates, so checking each value decides the cell in both directions. An enum of
  arrays or objects is left to valgebra: each number inside one has two spellings.
- **Interval arithmetic decides range cells.** Where every predicate bearing on a cell of
  the integer or fraction kind is a range — `type`, bounds and an integral `multipleOf`,
  nothing else — the cell is a question about intervals, decided exactly over the integers
  or over the reals minus the integers (`valplan/ranges.py`), and a member is constructed
  where it is non-empty. The fraction kind also holds `NaN` and the two infinities, which
  `json.loads` returns: `NaN` lies only in a range without bounds, an infinity only past
  the open side, and the rule decides the three exactly. A step makes a range a lattice: which integers a cell holds
  repeats with the least common multiple of its steps, so one period decides it, and a
  period of more than 100000 multiples is left to valgebra. Where other predicates bear on
  the cell too, its ranges alone still prove it empty when they leave no number: leaving
  predicates out of a meet gives a superset.

A cell valgebra proves empty is dropped. A cell a concrete value falls in is *inhabited*;
the values come from the listed constants, from a fixed set of generic values at the
edges of common bounds, and from a sampler that draws candidates from each slot's schema
(`valplan/sample.py`), and membership is the only judge. Every other
cell is *undecided* and kept: it may be empty, so the planner must still cover it.
Keeping it can make the planner miss a program; it cannot make it accept a wrong one.

## The planner

The state is the variables the agent holds, each typed by its cells (`valplan/synth.py`).

- A **call** is enabled when every required argument can be bound to a variable whose
  cells all lie inside the argument's cells, and the assembled argument record lies inside
  the whole input schema. For a plain input schema — each property constrained on its own,
  nothing across them — the per-argument checks imply it; otherwise valgebra must prove
  it. A call adds the guaranteed result fields as variables.
- A **guarded call** handles a variable an argument only overlaps: `if v in tool.arg`, the
  *then* branch calls the tool with `v` narrowed to the overlap, and the *else* branch
  continues with `v` narrowed to the rest.
- A program is **strong** when every path reaches the goal: strong planning under the
  nondeterminism of tool outputs (Cimatti, Pistore, Roveri and Traverso 2003), with the
  outcomes partitioned by the cells rather than enumerated.

The search deepens iteratively on the calls and tests along a path, so the first program
found is a shallowest one. Calls no later step reads are then removed, each remaining call
moves into the one branch of a later test that reads it — a path should not make a call
it does not need, since a call can act on the world — and the program is checked once more
over the cells before it is returned.

Where no strong program exists within the depth, the same search lets an *else* branch
stop when its *then* branch succeeds, and each stop then gets its own search for a
continuation within the depth its path has left: a strong one, or one whose first test
narrows the stopped variable further. A stop therefore means "this program does not cover
these values", not "no program can": a deeper search or a decided cell may cover them.
Each stop is reported with the cells its variable is narrowed to there: every uncovered
value when those cells lie inside a predicate that lists its values, examples and a count
of undecided cells otherwise (`valplan.synth.gaps`).

## Why a program is sound

Each binding is accepted only on a proof: cell inclusion, which implies inclusion of the
predicates, plus the whole input record. The proofs come from valgebra and from three
exact rules in this package — pairwise relations proven by valgebra, enumeration of listed
values, interval arithmetic — each tested on its own. A static type test on a value
narrows by set difference over a partition, so the two branches together cover every value and overlap in
none. An undecided cell is kept and covered.

The verifier (`valplan/verify.py`) checks every program again with valgebra alone, without
the cells, the search or the three rules. It shares the compiler and valgebra with the
planner, so it checks the planning and not those two; the compiler is checked against the
test suite and the `jsonschema` package, and valgebra's proofs against every drawn value
(`tests/test_properties.py`). Where only the interval rule proves a link — valgebra does
not decide the complement of an integer range whose float spelling is admitted — the
verifier reports `undecided` for it.

## Limits

- **Types are the specification.** Two slots with the same schema cannot be told apart: a
  task's `subject` string and a customer `name` string are interchangeable to the planner.
  Distinct schemas — patterns, enums, ranges — are what make a plan mean what it should.
- **What is not modelled.** Side effects beyond "a call happens", tool errors (an MCP
  result with `isError`, a missing `structuredContent`), constants written into a call, and
  a result field the output schema does not guarantee: an optional one, one inside an
  optional object, or one past three levels. "Whatever the tools return" means whatever
  values inside their output schemas.
- **Search bounds.** The planner searches to a depth bound (6 calls and tests per path by
  default) over the cells it could decide. A guarded call's other arguments must be held
  when its test is made, so a call only the *then* branch needs counts on the *else* path
  too, and a program within the bound can need a deeper search to be found. Of each call
  it takes the first binding whose argument record checks, among at most 16 candidates
  (`MAX_BINDINGS`): a result's type does not depend on the binding, so one stands for all,
  and a library whose first 16 candidates all fail the record check can hide a program.
- **Opaque keywords.** A slot that uses `patternProperties`, `propertyNames`,
  `uniqueItems`, `min/maxContains` or a fractional `multipleOf` has exact membership but
  leaves relations through it undecided ([`02-compiler.md`](02-compiler.md)).
