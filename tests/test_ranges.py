import random
from fractions import Fraction

import pytest

from valplan.abstraction import Abstraction
from valplan.ranges import (
    PERIOD_LIMIT,
    PeriodTooLongError,
    fractions_empty,
    integer_member,
    integers_empty,
    member,
)
from valplan.schema import Interval, compile_schema, interval


def _i(lo, hi, *, integer=True, lo_open=False, hi_open=False, step=None):
    return Interval(
        integer,
        None if lo is None else Fraction(lo),
        lo_open,
        None if hi is None else Fraction(hi),
        hi_open,
        step,
    )


def _holds(n, r):
    lo_ok = r.low is None or n > r.low or (n == r.low and not r.low_open)
    hi_ok = r.high is None or n < r.high or (n == r.high and not r.high_open)
    return lo_ok and hi_ok and (r.step is None or n % r.step == 0)


def _random_range(rng):
    lo = rng.choice([None, *range(-30, 31)])
    hi = rng.choice([None, *range(-30, 31)])
    step = rng.choice([None, None, 1, 2, 3, 4, 5, 6])
    return _i(lo, hi, lo_open=rng.random() < 0.3, hi_open=rng.random() < 0.3, step=step)


class TestIntegers:
    def test_a_range_minus_a_covering_range_is_empty(self):
        assert integers_empty([_i(1, 30)], [_i(1, 500000)])

    def test_a_gap_between_holes_is_found(self):
        assert not integers_empty([_i(1, 10)], [_i(1, 4), _i(6, 10)])
        assert integers_empty([_i(1, 10)], [_i(1, 5), _i(6, 10)])

    def test_open_bounds_exclude_their_integer(self):
        assert integers_empty([_i(1, 2, lo_open=True, hi_open=True)], [])
        assert not integers_empty([_i(1, 3, lo_open=True, hi_open=True)], [])

    def test_unbounded_sides_are_infinite(self):
        assert not integers_empty([_i(None, None)], [_i(None, 0)])
        assert integers_empty([_i(None, None)], [_i(None, 0), _i(1, None)])


class TestLattices:
    def test_a_step_keeps_only_its_multiples(self):
        assert integer_member([_i(5, 30, step=5)], [_i(1, 9)]) == 10
        assert integers_empty([_i(5, 30, step=5)], [_i(1, 9), _i(11, 30)]) is False
        assert integers_empty([_i(5, 30, step=5)], [_i(1, 30)])

    def test_steps_meet_in_their_least_common_multiple(self):
        assert integer_member([_i(1, None, step=4), _i(None, None, step=6)], []) == 12
        assert integers_empty([_i(1, 11, step=4), _i(None, None, step=6)], [])

    def test_a_stepped_hole_removes_only_its_multiples(self):
        assert integer_member([_i(10, 10)], [_i(None, None, step=3)]) == 10
        assert integers_empty([_i(9, 9)], [_i(None, None, step=3)])
        assert integers_empty([_i(None, None, step=6)], [_i(None, None, step=3)])

    def test_unbounded_lattices_are_decided_by_one_period(self):
        assert integer_member([_i(None, -1, step=7)], [_i(None, None, step=2)]) == -7
        assert integers_empty([_i(None, None, step=2)], [_i(None, None, step=1)])

    def test_a_period_longer_than_the_limit_is_refused(self):
        steps = [101, 103, 107]
        with pytest.raises(PeriodTooLongError):
            integer_member([_i(None, None)], [_i(None, None, step=s) for s in steps])
        assert PERIOD_LIMIT < 101 * 103 * 107

    def test_every_answer_agrees_with_enumeration(self):
        # Bounds lie in [-30, 30] and steps divide 60, so membership outside the window
        # repeats with period 60: a member exists iff one exists within [-90, 90].
        rng = random.Random(0)
        for _ in range(3000):
            pos = [_random_range(rng) for _ in range(rng.randrange(1, 4))]
            neg = [_random_range(rng) for _ in range(rng.randrange(4))]
            window = range(-90, 91)
            exists = any(
                all(_holds(n, r) for r in pos) and not any(_holds(n, r) for r in neg)
                for n in window
            )
            found = integer_member(pos, neg)
            assert (found is not None) == exists, (pos, neg)
            if found is not None:
                assert all(_holds(found, r) for r in pos)
                assert not any(_holds(found, r) for r in neg)


class TestFractions:
    def test_a_unit_range_holds_non_integers(self):
        assert not fractions_empty([_i(0, 1, integer=False)], [])

    def test_an_integer_range_holds_none(self):
        assert fractions_empty([_i(0, 1)], [])

    def test_a_point_is_a_fraction_only_if_it_is_not_an_integer(self):
        assert fractions_empty([_i(2, 2, integer=False)], [])
        assert not fractions_empty([_i("2.5", "2.5", integer=False)], [])

    def test_holes_can_cover_a_range(self):
        whole = _i(0, 10, integer=False)
        assert fractions_empty([whole], [_i(0, 5, integer=False), _i(5, 10, integer=False)])
        open_halves = [
            _i(0, 5, integer=False, hi_open=True),
            _i(5, 10, integer=False, lo_open=True),
        ]
        assert fractions_empty([whole], open_halves)

    def test_a_stepped_range_holds_no_fraction_and_excludes_none(self):
        assert fractions_empty([_i(0, 10, integer=False, step=2)], [])
        assert not fractions_empty([_i(0, 1, integer=False)], [_i(None, None, step=1)])
        assert member([_i(0, 1, integer=False)], [_i(None, None, step=1)], integer=False) == 0.5


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "integer", "minimum": 1, "maximum": 30}, _i(1, 30)),
        ({"type": "number", "exclusiveMinimum": 0}, _i(0, None, integer=False, lo_open=True)),
        ({"type": "integer", "minimum": 1, "exclusiveMinimum": 1}, _i(1, None, lo_open=True)),
        ({"type": "integer", "multipleOf": 2}, _i(None, None, step=2)),
        ({"type": "number", "minimum": 0, "multipleOf": 5.0}, _i(0, None, integer=False, step=5)),
        ({"type": "number", "multipleOf": 0.5}, None),
        ({"type": "string"}, None),
    ],
)
def test_interval_reads_a_range_schema_and_nothing_else(schema, expected):
    assert interval(schema) == expected


def test_nested_ranges_give_one_cell_per_interval_and_none_undecided():
    schemas = [
        {"type": "integer", "minimum": 1, "maximum": 500000},
        {"type": "integer", "minimum": 1, "maximum": 30},
        {"type": "integer", "minimum": 31, "maximum": 1000000},
    ]
    preds = [compile_schema(s) for s in schemas]
    ranges = {p: r for p, s in zip(preds, schemas, strict=True) if (r := interval(s)) is not None}
    a = Abstraction(preds, ranges=ranges)
    integer_cells = [c for c in a.cells if c.kind == "integer"]
    assert len(integer_cells) == 4
    assert all(c.status == "inhabited" for c in a.cells)


def test_a_stepped_range_leaves_no_cell_undecided():
    schemas = [
        {"type": "integer", "minimum": 1},
        {"type": "number", "minimum": 0, "maximum": 30},
        {"type": "integer", "minimum": 1, "maximum": 500000},
        {"type": "integer", "minimum": 5, "maximum": 30, "multipleOf": 5},
    ]
    preds = [compile_schema(s) for s in schemas]
    ranges = {p: r for p, s in zip(preds, schemas, strict=True) if (r := interval(s)) is not None}
    a = Abstraction(preds, ranges=ranges)
    assert a.counts()["undecided"] == 0


def test_ranges_prove_a_cell_empty_where_another_predicate_bears_on_it():
    # No pair settles the cell: the meet of two ranges, 1 to 30, lies inside the third, and
    # neither range alone does. The fractional step comes first, so it bears on every split
    # after it, and valgebra decides nothing through an opaque predicate; the ranges alone
    # prove the cell empty.
    schemas = [
        {"type": "number", "multipleOf": 0.25},
        {"type": "integer", "minimum": 1},
        {"type": "number", "minimum": 0, "maximum": 30},
        {"type": "integer", "minimum": 1, "maximum": 500000},
    ]
    preds = [compile_schema(s) for s in schemas]
    ranges = {p: r for p, s in zip(preds, schemas, strict=True) if (r := interval(s)) is not None}
    a = Abstraction(preds, ranges=ranges)
    inside_both_outside_third = [
        c for c in a.cells if c.kind == "integer" and {1, 2} <= c.inside and 3 not in c.inside
    ]
    assert inside_both_outside_third == []


class TestBounds:
    def test_a_float_bound_is_the_double_json_loads_returns(self):
        assert interval({"type": "integer", "minimum": 1e23}) == _i(int(1e23), None)
        tenth = _i(None, Fraction(0.1), integer=False)
        assert interval({"type": "number", "maximum": 0.1}) == tenth

    def test_a_non_finite_bound_is_not_a_range(self):
        assert interval({"type": "number", "maximum": float("inf")}) is None

    def test_the_integers_between_a_double_and_its_decimal_are_a_cell(self):
        # 1e23 parses to 99999999999999991611392, so a minimum of 1e23 admits the 8388608
        # integers below 10**23 that a minimum of 10**23 refuses.
        schemas = [{"type": "integer", "minimum": 1e23}, {"type": "integer", "minimum": 10**23}]
        preds = [compile_schema(s) for s in schemas]
        profiles = [interval(s) for s in schemas]
        ranges = {p: r for p, r in zip(preds, profiles, strict=True) if r is not None}
        a = Abstraction(preds, ranges=ranges)
        between = [c for c in a.cells if c.kind == "integer" and c.inside == frozenset({0})]
        assert len(between) == 1
        assert between[0].status == "inhabited"
        assert preds[0].is_valid(between[0].witness)
        assert not preds[1].is_valid(between[0].witness)
