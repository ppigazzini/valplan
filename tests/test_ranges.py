from fractions import Fraction

import pytest

from valplan.abstraction import Abstraction
from valplan.ranges import fractions_empty, integers_empty
from valplan.schema import Interval, compile_schema, interval


def _i(lo, hi, *, integer=True, lo_open=False, hi_open=False):
    return Interval(
        integer,
        None if lo is None else Fraction(lo),
        lo_open,
        None if hi is None else Fraction(hi),
        hi_open,
    )


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


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"type": "integer", "minimum": 1, "maximum": 30}, _i(1, 30)),
        ({"type": "number", "exclusiveMinimum": 0}, _i(0, None, integer=False, lo_open=True)),
        ({"type": "integer", "minimum": 1, "exclusiveMinimum": 1}, _i(1, None, lo_open=True)),
        ({"type": "integer", "multipleOf": 2}, None),
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
