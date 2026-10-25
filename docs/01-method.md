# Method

## Contracts as typed slots

An agent does not pass one tool's result to the next whole; it fills each argument from a
value it holds. `valplan/contracts.py` reads each tool as slots: one per argument, one per
result field the output schema requires. Each slot's set is its property's subschema,
compiled by `valplan/schema.py`. A constraint the whole input object carries is kept: a
binding is accepted only if the assembled argument record is proven inside the tool's
whole input schema.

## The abstraction

Every slot schema, task input and goal is a predicate on JSON values. Their minterms —
each predicate taken positively or negatively — partition the JSON values into cells, and
each predicate is exactly a union of cells (`valplan/abstraction.py`). Inclusion between
the cells of two predicates implies inclusion between the predicates; the converse fails
only through an undecided cell inside one and outside the other. Narrowing a value by a
runtime test is set difference. This is predicate abstraction (Graf and Saidi 1997) over a
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
  predicate a cell holds exactly the listed values that meet the rest of its predicates,
  so checking each value decides the cell in both directions.

A cell valgebra proves empty is dropped. A cell a concrete value falls in is *inhabited*;
the values come from the listed constants, from a fixed set of generic values at the
edges of common bounds, and from a sampler that draws candidates from each slot's schema
(`valplan/sample.py`), and membership is the only judge. Every other
cell is *undecided* and kept: it may be empty, so the planner must still cover it.
Keeping it can make the planner miss a program; it cannot make it accept a wrong one.

## The planner

The state is the variables the agent holds, each typed by its cells (`valplan/synth.py`).

- A **call** is enabled when every required argument can be bound to a variable whose
  cells all lie inside the argument's cells, and the assembled argument record is proven
  inside the whole input schema. It adds the guaranteed result fields as variables.
- A **guarded call** handles a variable an argument only overlaps: `if v in tool.arg`, the
  *then* branch calls the tool with `v` narrowed to the overlap, and the *else* branch
  continues with `v` narrowed to the rest.
- A program is **strong** when every path reaches the goal: strong planning under the
  nondeterminism of tool outputs (Cimatti, Pistore, Roveri and Traverso 2003), with the
  outcomes partitioned by the cells rather than enumerated.

The search deepens iteratively on the calls and tests along a path, so the first program
found is a shallowest one; calls no later step reads are then removed, and the program is
checked once more over the cells before it is returned. Where no strong program exists
within the depth, the same search lets an *else* branch stop when its *then* branch
succeeds. Each stop is reported with the cells its variable is narrowed to there: every
uncovered value when those cells lie inside a predicate that lists its values, examples
and a count of undecided cells otherwise (`valplan.synth.gaps`).

## Why a program is sound

Each binding is accepted only on a proof: cell inclusion, which holds exactly when the
predicates are included, plus a valgebra proof for the whole input record. A runtime test
narrows by set difference over a partition, so the two branches together cover every
value and overlap in none. An undecided cell is kept and covered. The verifier
(`valplan/verify.py`) checks every program again with valgebra directly, sharing no code
with the cells, and the tests require it to prove every check the planner relied on.

## Limits

- **Types are the specification.** Two slots with the same schema cannot be told apart: a
  task's `subject` string and a customer `name` string are interchangeable to the planner.
  Distinct schemas — patterns, enums, ranges — are what make a plan mean what it should.
- **Search bounds.** The planner is complete up to its depth bound (6 calls and tests per
  path by default), over the cells it could decide, and over the first 16 argument
  bindings of each call (`MAX_BINDINGS`); a library where more than 16 bindings of one
  call type-check can hide a program.
- **Opaque keywords.** A slot that uses `patternProperties`, `propertyNames`,
  `uniqueItems`, `min/maxContains` or a fractional `multipleOf` has exact membership but
  leaves relations through it undecided ([`02-compiler.md`](02-compiler.md)).
