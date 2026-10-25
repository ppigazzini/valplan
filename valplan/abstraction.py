"""Predicate abstraction: the finite Boolean algebra a library's contracts generate.

Every slot schema of every tool, every task input and the goal is a predicate on JSON
values. The minterms of those predicates -- each predicate taken positively or
negatively -- partition the JSON universe into finitely many *cells*, and every predicate
is exactly a union of cells. Inclusion between the cells of two predicates implies
inclusion between the predicates, and narrowing a value by a runtime test is set
difference (Graf and Saidi 1997, over a Boolean algebra of semantic types rather than of
program states). The converse holds whenever no undecided cell lies in one predicate and
outside the other.

Building it is where the decision procedure works. A cell valgebra proves empty is
dropped. A cell a concrete JSON value falls in is *inhabited*, with the value kept as its
witness. Every other cell is *undecided*: kept, because valgebra could prove neither, and
counted, because an undecided cell is either a spurious one the planner must still cover
or a precision gap in the procedure. Keeping it is what makes every plan sound; it can
only make the planner miss a plan, never accept a wrong one.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from valplan._valgebra import Validator, complement, intersection
from valplan.ranges import fractions_empty, integers_empty, member
from valplan.schema import (
    ARRAY,
    BOOLEAN,
    INTEGER,
    JSON,
    NULL,
    NUMBER,
    OBJECT,
    STRING,
    Interval,
    json_key,
)

type Status = Literal["inhabited", "undecided"]
type Cells = frozenset[int]

#: The JSON universe as seven disjoint kinds. Cells start here, one per kind, and a
#: predicate splits only the cells of the kinds it meets: a string pattern leaves an
#: integer cell as it is, with no complement term added to it. Every cell's set then
#: carries only the predicates of its own kind, which is what keeps each emptiness
#: question as small as the contracts that bear on it.
KINDS: tuple[tuple[str, Validator[Any]], ...] = (
    ("null", NULL),
    ("boolean", BOOLEAN),
    ("integer", INTEGER),
    ("fraction", intersection(NUMBER, complement(INTEGER))),
    ("string", STRING),
    ("array", ARRAY),
    ("object", OBJECT),
)

#: Values tried in every abstraction besides the ones drawn from the schemas: the cells
#: outside every predicate, and at the edges of common bounds, are where no schema's own
#: draw lands.
GENERIC: tuple[Any, ...] = (
    None,
    True,
    False,
    0,
    -1,
    1,
    7,
    10**9,
    -(10**9),
    0.5,
    -2.5,
    1e300,
    "",
    " ",
    "!",
    "a",
    "A1",
    "x" * 64,
    "x" * 300,
    "\n",
    "é",
    "9",
    [],
    [None],
    [1, 2],
    {},
    {"k": 1},
)


class SoundnessError(AssertionError):
    """A concrete value fell in a cell the decision procedure called empty."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One minterm: the predicates containing it, its exact set, and what is known of it."""

    inside: frozenset[int]
    kind: str = ""
    validator: Validator[Any] = field(compare=False, repr=False, default=JSON)
    status: Status = "undecided"
    witness: Any = field(compare=False, default=None)


class Abstraction:
    """The cells of a set of predicates, with a witness wherever one was found."""

    def __init__(
        self,
        predicates: Sequence[Validator[Any]],
        witnesses: Iterable[Any] = (),
        finite: Mapping[Validator[Any], Sequence[Any]] | None = None,
        ranges: Mapping[Validator[Any], Interval] | None = None,
    ) -> None:
        self.predicates: list[Validator[Any]] = []
        self._ids: dict[Validator[Any], int] = {}
        for p in predicates:
            self.add(p)
        self._finite = {
            self._ids[p]: list(values) for p, values in (finite or {}).items() if p in self._ids
        }
        self._ranges = {self._ids[p]: r for p, r in (ranges or {}).items() if p in self._ids}
        self._meets: dict[int, set[str]] = {}
        #: Members the range arithmetic constructed while deciding cells non-empty.
        self._found: list[Any] = []
        self.cells: list[Cell] = self._split()
        listed = [v for values in self._finite.values() for v in values]
        self._classify([*listed, *GENERIC, *self._found, *witnesses])
        self._members = [
            frozenset(i for i, c in enumerate(self.cells) if p in c.inside)
            for p in range(len(self.predicates))
        ]

    def add(self, predicate: Validator[Any]) -> int:
        """Register ``predicate`` before the cells are built, and return its index.

        Predicates equal in valgebra's normal form share one index, so a schema repeated
        across tools splits the universe once.
        """
        if predicate not in self._ids:
            self._ids[predicate] = len(self.predicates)
            self.predicates.append(predicate)
        return self._ids[predicate]

    def _disjoint(self, i: int, j: int) -> bool:
        key = (min(i, j), max(i, j))
        if key not in self._apart:
            self._apart[key] = intersection(self.predicates[i], self.predicates[j]).is_empty()
        return self._apart[key]

    def _below(self, i: int, j: int) -> bool:
        if (i, j) not in self._under:
            self._under[i, j] = self.predicates[i].is_subtype_of(self.predicates[j])
        return self._under[i, j]

    def _set(
        self, kind: Validator[Any], pos: frozenset[int], neg: frozenset[int]
    ) -> Validator[Any]:
        """Return a cell's set, leaving out every complement a positive member implies.

        A predicate disjoint from one the cell lies in is already excluded by it, so its
        complement adds a term to every later question and no information.
        """
        kept = [q for q in sorted(neg) if not any(self._disjoint(q, p) for p in pos)]
        return intersection(
            kind,
            *(self.predicates[p] for p in sorted(pos)),
            *(complement(self.predicates[q]) for q in kept),
        )

    def _empty(self, kind: Validator[Any], pos: frozenset[int], neg: frozenset[int]) -> bool:
        """Return whether the cell is proven empty.

        Inside a predicate that lists its values, the cell holds exactly the listed values
        that meet the rest of its predicates, so checking each value decides it both ways.
        Elsewhere valgebra decides, and a cell it cannot prove empty is kept.
        """
        for p in sorted(pos):
            if p in self._finite:
                return not any(
                    kind.is_valid(v)
                    and all(self.predicates[q].is_valid(v) for q in pos)
                    and not any(self.predicates[q].is_valid(v) for q in neg)
                    for v in self._finite[p]
                )
        name = next(n for n, k in KINDS if k is kind)
        if name in {"integer", "fraction"}:
            bearing = [q for q in pos | neg if name in self._meets.get(q, {name})]
            if all(q in self._ranges for q in bearing):
                ins = [self._ranges[q] for q in pos]
                outs = [self._ranges[q] for q in neg if q in bearing]
                empty = (
                    integers_empty(ins, outs) if name == "integer" else fractions_empty(ins, outs)
                )
                if not empty:
                    found = member(ins, outs, integer=name == "integer")
                    if found is not None:
                        self._found.append(found)
                return empty
        return self._set(kind, pos, neg).is_empty()

    def _split(self) -> list[Cell]:
        """Split the kinds by every predicate in turn.

        A split is first settled from relations proven between pairs of predicates, each
        decided once: a cell inside a predicate disjoint from ``p`` is outside ``p``, a cell
        inside a predicate below ``p`` is inside it, and a cell outside a predicate above
        ``p`` is outside it. Only a split no pair settles asks valgebra about the cell's
        whole set. A pairwise proof is a proof about every cell it covers, so the shortcut
        is exact, and it keeps the questions valgebra is asked as small as the contracts.
        """
        self._apart: dict[tuple[int, int], bool] = {}
        self._under: dict[tuple[int, int], bool] = {}
        kinds = dict(KINDS)
        cells = [(frozenset[int](), frozenset[int](), name) for name in kinds]
        for i, p in enumerate(self.predicates):
            meets = {name for name, kind in kinds.items() if not intersection(kind, p).is_empty()}
            self._meets[i] = meets
            out: list[tuple[frozenset[int], frozenset[int], str]] = []
            for pos, neg, name in cells:
                if name not in meets or any(self._disjoint(i, j) for j in pos):
                    out.append((pos, neg | {i}, name))
                elif any(self._below(j, i) for j in pos):
                    out.append((pos | {i}, neg, name))
                elif any(self._below(i, j) for j in neg):
                    out.append((pos, neg | {i}, name))
                else:
                    if not self._empty(kinds[name], pos | {i}, neg):
                        out.append((pos | {i}, neg, name))
                    if not self._empty(kinds[name], pos, neg | {i}):
                        out.append((pos, neg | {i}, name))
            cells = out
        return [Cell(pos, name, self._set(kinds[name], pos, neg)) for pos, neg, name in cells]

    def _classify(self, witnesses: Iterable[Any]) -> None:
        index = {(c.kind, c.inside): n for n, c in enumerate(self.cells)}
        for w in witnesses:
            kinds = [name for name, kind in KINDS if kind.is_valid(w)]
            if len(kinds) != 1:
                continue
            inside = frozenset(i for i, p in enumerate(self.predicates) if p.is_valid(w))
            n = index.get((kinds[0], inside))
            if n is None:
                msg = f"{w!r} lies in a minterm proven empty: {sorted(inside)}"
                raise SoundnessError(msg)
            cell = self.cells[n]
            if cell.status == "undecided":
                self.cells[n] = Cell(inside, cell.kind, cell.validator, "inhabited", w)

    def cell_of(self, value: Any) -> int | None:
        """Return the cell ``value`` lies in, or None for a value outside the JSON kinds."""
        kinds = [name for name, kind in KINDS if kind.is_valid(value)]
        if len(kinds) != 1:
            return None
        inside = frozenset(i for i, p in enumerate(self.predicates) if p.is_valid(value))
        for n, c in enumerate(self.cells):
            if c.kind == kinds[0] and c.inside == inside:
                return n
        return None

    def members(self, cells: Cells) -> tuple[list[Any], bool]:
        """Return known members of ``cells``, and whether they are all of them.

        A cell inside a predicate that lists its values holds exactly the listed values that
        fall in it, so the list is complete when every cell is such a cell. Otherwise the
        witnesses are examples, one per inhabited cell.
        """
        complete = all(self.cells[c].inside & self._finite.keys() for c in cells)
        seen: list[Any] = []
        if complete:
            for values in self._finite.values():
                for v in values:
                    if self.cell_of(v) in cells and not any(_same(v, s) for s in seen):
                        seen.append(v)
            return seen, True
        seen += [
            self.cells[c].witness for c in sorted(cells) if self.cells[c].status == "inhabited"
        ]
        return seen, False

    def index(self, predicate: Validator[Any]) -> int:
        """Return the index of a registered predicate."""
        return self._ids[predicate]

    def cells_of(self, predicate: Validator[Any]) -> Cells:
        """Return the cells whose union is ``predicate``."""
        return self._members[self._ids[predicate]]

    def counts(self) -> dict[str, int]:
        """Return how many predicates and cells there are, by status."""
        inhabited = sum(c.status == "inhabited" for c in self.cells)
        return {
            "predicates": len(self.predicates),
            "cells": len(self.cells),
            "inhabited": inhabited,
            "undecided": len(self.cells) - inhabited,
            "minterms": 2 ** len(self.predicates),
        }


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and json_key(a) == json_key(b)
