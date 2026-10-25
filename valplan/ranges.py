"""Exact emptiness of a cell carved from numeric ranges, by interval arithmetic.

A cell of the integer kind inside ranges ``pos`` and outside ranges ``neg`` holds the
integers in every ``pos`` range and in no ``neg`` range: a question about integer
intervals. A range with a step (an integral ``multipleOf``) is a lattice, the multiples of
the step within its bounds, and the question stays exact: which integers a cell holds
repeats with the least common multiple of the steps bearing on it. A cell of the fraction
kind holds the non-integer numbers likewise: a question about real intervals, minus the
integers, in which a stepped range holds nothing. Both are decided exactly here.

Python's numbers are a subset of the reals, so a range question answered "empty" over
the reals is empty over the floats too. The converse can fail -- ``(0, 5e-324)`` holds
reals and no float -- and then the cell is kept, which costs completeness, never
soundness. Python's integers are every integer, so the integer kind has no such gap.
"""

import itertools
import math
from collections.abc import Sequence
from fractions import Fraction

from valplan.schema import Interval

type Bound = Fraction | float
type End = int | float

#: How many multiples of a cell's common step one piece of it may need walked before the
#: question is left to valgebra. The walk is one period: the least common multiple of the
#: steps, divided by the common step. Coprime steps of a few hundred each make one longer
#: than is worth walking, and the cell is then decided elsewhere or kept undecided.
PERIOD_LIMIT = 100_000


class PeriodTooLongError(ValueError):
    """A stepped cell repeats over more multiples than `PERIOD_LIMIT` allows walking."""


def _span(r: Interval) -> tuple[End, End]:
    """Return the first and last integer in ``r``'s bounds, infinite where it is unbounded."""
    if r.low is None:
        first: End = -math.inf
    else:
        first = math.ceil(r.low)
        if r.low_open and first == r.low:
            first += 1
    if r.high is None:
        last: End = math.inf
    else:
        last = math.floor(r.high)
        if r.high_open and last == r.high:
            last -= 1
    return first, last


def _remove(piece: tuple[End, End], hole: tuple[End, End]) -> list[tuple[End, End]]:
    """Return the integers of ``piece`` outside ``hole``, as at most two pieces."""
    low, high = piece
    out = [(low, min(high, hole[0] - 1)), (max(low, hole[1] + 1), high)]
    # A hole reaching an infinity leaves (-inf, -inf) or (inf, inf) on that side: no integer.
    return [(a, b) for a, b in out if a <= b and a < math.inf and b > -math.inf]


def _walk(low: End, high: End, step: int, holes: Sequence[int]) -> int | None:
    """Return a multiple of ``step`` in ``[low, high]`` that no step in ``holes`` divides.

    Whether a multiple qualifies repeats with ``lcm(step, *holes)``, so one period of
    multiples from either end decides it.
    """
    period = math.lcm(step, *holes) // step
    if low == -math.inf and high == math.inf:
        start, direction, count = 0, 1, period
    elif low == -math.inf:
        start, direction, count = int(high) // step * step, -1, period
    else:
        start, direction = -(-int(low) // step) * step, 1
        count = period if high == math.inf else max(0, min(period, (high - start) // step + 1))
    if count > PERIOD_LIMIT:
        msg = f"{count} multiples of {step} to walk"
        raise PeriodTooLongError(msg)
    for k in range(int(count)):
        n = start + direction * k * step
        if all(n % s for s in holes):
            return n
    return None


def integer_member(pos: Sequence[Interval], neg: Sequence[Interval]) -> int | None:
    """Return an integer in every range of ``pos`` and in no range of ``neg``, or None.

    None means there is no such integer. The bounds of every ``pos`` range meet into one
    span; each unstepped ``neg`` range removes its integers from it; each stepped one cuts
    the rest into pieces over which the same steps exclude, and one period of each piece is
    walked. Raise `PeriodTooLongError` where a period exceeds `PERIOD_LIMIT` multiples.
    """
    spans = [_span(r) for r in pos]
    first = max((s[0] for s in spans), default=-math.inf)
    last = min((s[1] for s in spans), default=math.inf)
    if first > last:
        return None
    step = math.lcm(*(r.step for r in pos if r.step is not None))
    pieces = [(first, last)]
    for r in neg:
        if r.step is None:
            pieces = [p for piece in pieces for p in _remove(piece, _span(r))]
    lattices = [(_span(r), r.step) for r in neg if r.step is not None]
    for low, high in pieces:
        cuts = sorted(
            {b for (a, z), _ in lattices for b in (a, z + 1) if low < b <= high} - {math.inf}
        )
        for a, z in itertools.pairwise([low, *cuts, high + 1]):
            holes = [s for (lo, hi), s in lattices if lo <= a and z - 1 <= hi]
            found = _walk(a, z - 1, step, holes)
            if found is not None:
                return found
    return None


def integers_empty(pos: Sequence[Interval], neg: Sequence[Interval]) -> bool:
    """Return whether no integer lies in every range of ``pos`` and in no range of ``neg``.

    Raise `PeriodTooLongError` where the steps make the question too long to walk.
    """
    return integer_member(pos, neg) is None


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
    """Return whether no non-integer number lies in every ``pos`` range and no ``neg`` one.

    A stepped range holds integers only: inside one the cell is empty, and outside one
    excludes no non-integer.
    """
    whole: Piece = (-math.inf, True, math.inf, True)
    for r in pos:
        if r.integer or r.step is not None:
            return True
        whole = _meet(whole, _piece(r))
    pieces = [whole] if _nonempty(whole) else []
    for r in neg:
        if r.step is None:
            pieces = [q for p in pieces for q in _minus(p, _piece(r))]
    for low, low_open, high, high_open in pieces:
        if low < high:
            return False
        if not low_open and not high_open and Fraction(low) != math.floor(low):
            return False
    return True


def _holds(x: Fraction, r: Interval) -> bool:
    if r.step is not None and (x.denominator != 1 or x.numerator % r.step):
        return False
    if r.low is not None and (x < r.low or (r.low_open and x == r.low)):
        return False
    return not (r.high is not None and (x > r.high or (r.high_open and x == r.high)))


def member(pos: Sequence[Interval], neg: Sequence[Interval], *, integer: bool) -> float | None:
    """Return a number in every ``pos`` range and no ``neg`` one, of the kind asked, or None.

    An integer comes from `integer_member`. A non-integer is sought among the bounds of
    every range, half a step either side of them, and midpoints between them; a set of
    non-integers carved by finitely many intervals has a member among them whenever it has
    one at all, up to the float the member converts to. Each candidate is checked exactly,
    and as the float it would be returned as.
    """
    if integer:
        return integer_member(pos, neg)
    edges = sorted(
        {b for r in [*pos, *neg] for b in (r.low, r.high) if b is not None} | {Fraction(0)}
    )
    steps = [Fraction(1), Fraction(1, 2)]
    candidates: list[Fraction] = []
    for e in edges:
        candidates += [e, *(e + s for s in steps), *(e - s for s in steps)]
    candidates += [(a + b) / 2 for a, b in itertools.pairwise(edges)]
    for x in candidates:
        value = float(x)
        exact = Fraction(value)
        if exact.denominator == 1:
            continue
        if all(_holds(exact, r) for r in pos) and not any(_holds(exact, r) for r in neg):
            return value
    return None
