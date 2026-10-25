"""Exact emptiness of a cell carved from numeric ranges, by interval arithmetic.

A cell of the integer kind inside ranges ``pos`` and outside ranges ``neg`` holds the
integers in every ``pos`` range and in no ``neg`` range: a question about integer
intervals. A cell of the fraction kind holds the non-integer numbers likewise: a question
about real intervals, minus the integers. Both are decided exactly here.

Python's numbers are a subset of the reals, so a range question answered "empty" over
the reals is empty over the floats too. The converse can fail -- ``(0, 5e-324)`` holds
reals and no float -- and then the cell is kept, which costs completeness, never
soundness.
"""

import itertools
import math
from collections.abc import Sequence
from fractions import Fraction

from valplan.schema import Interval

type Bound = Fraction | float


def _integers(r: Interval) -> tuple[Bound, Bound]:
    """Return the first and last integer in ``r``, infinite where it is unbounded."""
    if r.low is None:
        first: Bound = -math.inf
    else:
        first = Fraction(math.ceil(r.low))
        if r.low_open and first == r.low:
            first += 1
    if r.high is None:
        last: Bound = math.inf
    else:
        last = Fraction(math.floor(r.high))
        if r.high_open and last == r.high:
            last -= 1
    return first, last


def integers_empty(pos: Sequence[Interval], neg: Sequence[Interval]) -> bool:
    """Return whether no integer lies in every range of ``pos`` and in no range of ``neg``."""
    spans = [_integers(r) for r in pos]
    first = max((s[0] for s in spans), default=-math.inf)
    last = min((s[1] for s in spans), default=math.inf)
    holes = sorted((_integers(r) for r in neg), key=lambda s: s[0])
    for low, high in holes:
        if low > first:
            break
        if high >= first:
            first = high + 1
    # A sweep past every integer ends at +inf, which no integer reaches whatever `last` is.
    return first > last or first == math.inf


type Piece = tuple[Bound, bool, Bound, bool]


def _piece(r: Interval) -> Piece:
    low = -math.inf if r.low is None else r.low
    high = math.inf if r.high is None else r.high
    return low, r.low_open or r.low is None, high, r.high_open or r.high is None


def _meet(a: Piece, b: Piece) -> Piece:
    low, low_open = max((a[0], a[1]), (b[0], b[1]), key=lambda x: (x[0], x[1]))
    high, high_open = min((a[2], not a[3]), (b[2], not b[3]), key=lambda x: (x[0], x[1]))
    return low, low_open, high, not high_open


def _nonempty(p: Piece) -> bool:
    low, low_open, high, high_open = p
    return low < high or (low == high and not low_open and not high_open)


def _minus(p: Piece, hole: Piece) -> list[Piece]:
    """Return the parts of ``p`` outside ``hole``."""
    low, low_open, high, high_open = p
    h_low, h_low_open, h_high, h_high_open = hole
    out = [(low, low_open, h_low, not h_low_open), (h_high, not h_high_open, high, high_open)]
    return [_meet(p, q) for q in out if _nonempty(_meet(p, q))]


def fractions_empty(pos: Sequence[Interval], neg: Sequence[Interval]) -> bool:
    """Return whether no non-integer number lies in every ``pos`` range and no ``neg`` one."""
    whole: Piece = (-math.inf, True, math.inf, True)
    for r in pos:
        if r.integer:
            return True
        whole = _meet(whole, _piece(r))
    pieces = [whole] if _nonempty(whole) else []
    for r in neg:
        pieces = [q for p in pieces for q in _minus(p, _piece(r))]
    for low, low_open, high, high_open in pieces:
        if low < high:
            return False
        if not low_open and not high_open and Fraction(low) != math.floor(low):
            return False
    return True


def _holds(x: Fraction, r: Interval) -> bool:
    if r.low is not None and (x < r.low or (r.low_open and x == r.low)):
        return False
    return not (r.high is not None and (x > r.high or (r.high_open and x == r.high)))


def member(pos: Sequence[Interval], neg: Sequence[Interval], *, integer: bool) -> float | None:
    """Return a number in every ``pos`` range and no ``neg`` one, of the kind asked, or None.

    Candidates are the bounds of every range, one step either side of them, and midpoints
    between them; a set of integers or of non-integers carved by finitely many intervals has
    a member among them whenever it has one at all, up to the float the member converts to.
    Each candidate is checked exactly, and as the float it would be returned as.
    """
    edges = sorted(
        {b for r in [*pos, *neg] for b in (r.low, r.high) if b is not None} | {Fraction(0)}
    )
    steps = [Fraction(1), Fraction(1, 2)] if not integer else [Fraction(1)]
    candidates: list[Fraction] = []
    for e in edges:
        candidates += [e, *(e + s for s in steps), *(e - s for s in steps)]
    candidates += [(a + b) / 2 for a, b in itertools.pairwise(edges)]
    for x in candidates:
        value: float = int(x) if integer and x.denominator == 1 else float(x)
        exact = Fraction(value)
        if integer and exact.denominator != 1:
            continue
        if not integer and exact.denominator == 1:
            continue
        if all(_holds(exact, r) for r in pos) and not any(_holds(exact, r) for r in neg):
            return value
    return None
