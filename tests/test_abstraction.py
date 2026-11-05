import math
import random
from typing import Annotated

import pytest
from annotated_types import Predicate
from valgebra import Validator, complement, intersection

import valplan.abstraction
from valplan.abstraction import Abstraction, SoundnessError
from valplan.contracts import tool
from valplan.sample import Sampler
from valplan.schema import Compiler, branches, compile_schema, finite, interval
from valplan.synth import Planner, witnesses


def _cell_of(abstraction, value):
    hits = [i for i, c in enumerate(abstraction.cells) if c.validator.is_valid(value)]
    assert len(hits) == 1, (value, hits)
    return hits[0]


class TestPartition:
    def test_every_value_lies_in_exactly_one_cell_and_predicates_are_unions_of_cells(
        self, library, tasks
    ):
        planner = Planner(
            library, tasks["settle-latest-invoice"], witnesses(library, tasks["ticket"])
        )
        a = planner.abstraction
        rng = random.Random(0)
        values = [
            *witnesses(library, tasks["ticket"], seed=1),
            "",
            "x" * 300,
            -5,
            2.5,
            None,
            [],
            {},
        ]
        for value in rng.sample(values, min(len(values), 150)):
            n = _cell_of(a, value)
            for p, pred in enumerate(a.predicates):
                assert pred.is_valid(value) == (n in a.cells_of(pred)), (value, p)

    def test_disjoint_patterns_split_linearly(self):
        preds = [
            compile_schema({"type": "string", "pattern": f"^{p}_[a-z]{{4}}$"})
            for p in ("cus", "sub", "in", "re", "cn", "di", "ms")
        ]
        a = Abstraction(preds)
        assert a.counts()["cells"] == 7 + len(preds)


class TestFiniteSets:
    def test_an_enum_cell_is_decided_by_its_listed_values(self):
        status = {"enum": ["open", "paid", "void"]}
        paid, opened = {"const": "paid"}, {"const": "open"}
        goal = {"anyOf": [{"type": "string", "pattern": "^re_"}, {"const": "void"}]}
        schemas = [status, paid, opened, goal]
        preds = [compile_schema(s) for s in schemas]
        listed = {
            p: values
            for p, s in zip(preds, schemas, strict=True)
            if (values := finite(s)) is not None
        }
        a = Abstraction(preds, finite=listed)
        assert len(a.cells_of(preds[0])) == 3
        assert all(a.cells[i].status == "inhabited" for i in a.cells_of(preds[0]))

    def test_finite_lists_both_spellings_of_an_integral_number(self):
        assert finite({"enum": [1, "a"]}) == [1, 1.0, "a"]
        assert finite({"type": "boolean"}) == [True, False]
        assert finite({"type": "string"}) is None

    def test_finite_lists_negative_zero_beside_zero(self):
        listed = finite({"const": 0})
        assert listed is not None
        assert [(type(v), math.copysign(1.0, v)) for v in listed] == [
            (int, 1.0),
            (float, 1.0),
            (float, -1.0),
        ]

    def test_a_cell_only_negative_zero_lies_in_is_kept(self):
        # Membership compares a float by value, so -0.0 lies in {"const": 0}; a predicate
        # written in Python tells it from 0.0, and the cell the two meet in holds it alone.
        zero = compile_schema({"const": 0})
        negative = Validator(Annotated[float, Predicate(lambda x: math.copysign(1.0, x) < 0)])
        listed = finite({"const": 0})
        assert listed is not None
        a = Abstraction([zero, negative], finite={zero: listed})
        assert a.cells_of(zero) & a.cells_of(negative)

    def test_finite_filters_by_the_rest_of_the_schema(self):
        assert finite({"enum": ["ab", "abcd"], "minLength": 3}) == ["abcd"]


def test_counts_add_up(library, tasks):
    a = Planner(library, tasks["ticket"], witnesses(library, tasks["ticket"])).abstraction
    c = a.counts()
    assert c["inhabited"] + c["undecided"] == c["cells"]
    assert c["cells"] < c["minterms"]
    assert intersection(a.cells[0].validator, a.cells[1].validator).is_empty()


def test_a_tool_without_arguments_reads_as_no_slots():
    t = tool(
        {
            "name": "ping",
            "inputSchema": {"type": "object"},
            "outputSchema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        }
    )
    assert t.args == ()
    assert [r.name for r in t.results] == ["ok"]


def test_the_sampler_draws_only_values_the_schema_admits(raw_tools):
    for spec in raw_tools:
        sampler = Sampler(spec["outputSchema"], random.Random(spec["name"]))
        compiled = compile_schema(spec["outputSchema"])
        drawn = sampler.draw(spec["outputSchema"], tries=50)
        assert drawn, spec["name"]
        assert all(compiled.is_valid(v) for v in drawn)


def _with_branches(*schemas):
    """Return the abstraction of ``schemas``, each union given its branches, as a planner's."""
    unions = {}
    for s in schemas:
        if (parts := branches(s)) is not None:
            compiler = Compiler(s)
            unions[compiler.compile(s)] = [compiler.compile(b) for b in parts]
    return Abstraction([compile_schema(s) for s in schemas], unions=unions)


def _cells(abstraction):
    return {(c.kind, c.inside) for c in abstraction.cells}


class TestUnions:
    def test_a_union_meets_only_the_kinds_its_branches_meet(self):
        ga = {"type": "string", "pattern": "^ga_[a-z0-9]{6}$"}
        gb = {"type": "string", "pattern": "^gb_[a-z0-9]{6}$"}
        preds = [compile_schema(s) for s in (ga, gb, {"anyOf": [ga, gb]}, {"type": "integer"})]
        a = Abstraction(preds, unions={preds[2]: [preds[0], preds[1]]})
        inside_union = [c for c in a.cells if 2 in c.inside]
        assert {c.kind for c in inside_union} == {"string"}
        assert all(c.inside & {0, 1} for c in inside_union)

    def test_a_nullable_integer_keeps_no_cell_of_booleans_inside_it(self):
        # valgebra leaves `boolean & (integer | null)` open whole and proves each branch's.
        nullable = {"type": ["integer", "null"]}
        whole = Abstraction([compile_schema(nullable)])
        assert ("boolean", frozenset({0})) in _cells(whole)
        assert ("boolean", frozenset({0})) not in _cells(_with_branches(nullable))

    def test_a_record_apart_from_each_branch_of_a_union_shares_no_cell_with_it(self):
        closed = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        }
        record = {"type": "object", "properties": {"p": {"type": "integer"}}, "required": ["p"]}
        nullable = {"anyOf": [{"type": "null"}, record]}
        whole = Abstraction([compile_schema(closed), compile_schema(nullable)])
        assert ("object", frozenset({0, 1})) in _cells(whole)
        assert ("object", frozenset({0, 1})) not in _cells(_with_branches(closed, nullable))

    def test_a_cell_only_the_whole_union_proves_empty_is_dropped(self):
        one = {"const": 1}
        everything = {"anyOf": [{"not": one}, one]}
        array = compile_schema({"type": "array"})
        parts = [compile_schema(b) for b in everything["anyOf"]]
        assert not intersection(array, *map(complement, parts)).is_empty()
        assert intersection(array, complement(compile_schema(everything))).is_empty()
        assert ("array", frozenset()) not in _cells(_with_branches(everything))

    def test_two_unions_past_the_definition_limit_together_are_decided_by_their_branches(self):
        # 70 definitions each: a branch pair holds 2, and the two whole unions 140.
        def trees(tag):
            return {"anyOf": [_tree(f"{tag}{i}", f"#/anyOf/{i}") for i in range(70)]}

        cells = _cells(_with_branches(trees("a"), trees("b")))
        assert ("object", frozenset({0})) in cells
        assert ("object", frozenset({1})) in cells
        assert ("object", frozenset({0, 1})) not in cells


class TestSamplerEdges:
    def _draw(self, schema, root=None):
        return Sampler(schema if root is None else root, random.Random(0)).draw(schema, 20)

    def test_an_empty_enum_draws_nothing(self):
        assert self._draw({"enum": []}) == []

    def test_a_pointer_with_a_list_index_or_an_escape_is_followed(self):
        root = {"allOf": [{"const": 3}], "$defs": {"a b": {"const": "x"}}}
        assert self._draw({"$ref": "#/allOf/0"}, root) == [3]
        assert self._draw({"$ref": "#/$defs/a%20b"}, root) == ["x"]

    def test_bounds_past_the_float_range_draw_without_overflow(self):
        assert all(v >= 10**400 for v in self._draw({"type": "number", "minimum": 10**400}))
        assert self._draw({"type": "number", "maximum": float("inf")})

    def test_a_brace_that_opens_no_count_is_a_literal(self):
        # The class ends at its escaped `]` to the sampler, which then meets `{\|}`.
        assert self._draw({"type": "string", "pattern": r"^[a\]{\|}]+$"}) is not None

    def test_a_huge_length_bound_draws_short_values(self):
        drawn = self._draw({"type": "string", "maxLength": 2**31 - 1})
        drawn += self._draw({"type": "array", "maxItems": 2**31 - 1})
        assert drawn
        assert all(len(v) <= 4096 for v in drawn)


def _tree(tag, pointer="#"):
    """Return a recursive schema of nodes tagged ``tag``: one valgebra definition."""
    kids = {"type": "array", "items": {"$ref": f"{pointer}/$defs/node"}}
    node = {
        "type": "object",
        "properties": {"tag": {"const": tag}, "kids": kids},
        "required": ["tag"],
    }
    return {"$defs": {"node": node}, "$ref": f"{pointer}/$defs/node"}


class TestDefinitionLimit:
    def test_cells_past_valgebras_definition_limit_are_kept_not_raised(self):
        # A cell outside 130 recursive schemas meets 130 definitions; valgebra builds 128.
        a = Abstraction([compile_schema(_tree(f"t{i}")) for i in range(130)])
        outside = [c for c in a.cells if c.kind == "object" and not c.inside]
        assert len(outside) == 1
        assert outside[0].status == "inhabited"

    def test_a_pair_whose_meet_is_past_the_limit_keeps_its_cell_undecided(self):
        # 70 definitions each compile; their meet holds 140, and valgebra builds 128.
        def wrapped(tag):
            trees = [_tree(f"{tag}{i}", f"#/allOf/0/anyOf/{i}") for i in range(70)]
            return {"allOf": [{"anyOf": trees}]}

        a = Abstraction([compile_schema(wrapped("a")), compile_schema(wrapped("b"))])
        meet = [c for c in a.cells if c.kind == "object" and c.inside == {0, 1}]
        assert [c.status for c in meet] == ["undecided"]


class TestSelfCheck:
    def test_a_false_emptiness_raises_where_a_witness_lands(self, monkeypatch):
        # Both halves of every split called empty: the string a witness is holds no cell.
        monkeypatch.setattr(Abstraction, "_empty", lambda *_: True)
        with pytest.raises(SoundnessError, match="lies in a minterm proven empty"):
            Abstraction([compile_schema({"type": "string", "minLength": 2})], ["ab"])

    def test_a_false_disjointness_raises_where_a_witness_lands(self, monkeypatch):
        monkeypatch.setattr(Abstraction, "_disjoint", lambda *_: True)
        preds = [compile_schema({"type": "string"}), compile_schema({"minLength": 1})]
        with pytest.raises(SoundnessError, match="lies in a minterm proven empty"):
            Abstraction(preds, ["ab"])


class TestFallbacks:
    def test_asking_unions_whole_keeps_every_cell_asking_them_a_branch_at_a_time_keeps(
        self, monkeypatch, library, tasks
    ):
        # Past `MAX_BRANCHES` a cell is asked about whole: valgebra proves less there, so
        # the cells kept can only grow, and every witness still lands in one.
        def cells():
            planner = Planner(
                library, tasks["vat-for-customer"], witnesses(library, tasks["vat-for-customer"])
            )
            return {(c.kind, c.inside) for c in planner.abstraction.cells}

        branchwise = cells()
        monkeypatch.setattr(valplan.abstraction, "MAX_BRANCHES", 0)
        assert cells() >= branchwise

    def test_a_union_with_a_branch_that_is_no_range_is_left_to_valgebra(self):
        union = {
            "anyOf": [{"type": "integer", "minimum": 0}, {"type": "number", "multipleOf": 0.5}]
        }
        below = {"type": "integer", "maximum": -1}
        u, r = compile_schema(union), compile_schema(below)
        parts = [compile_schema(b) for b in union["anyOf"]]
        ranges = {
            p: i for p, i in ((r, interval(below)), (parts[0], interval(union["anyOf"][0]))) if i
        }
        a = Abstraction([u, r], [-1], ranges=ranges, unions={u: parts})
        meet = a.cells_of(u) & a.cells_of(r)
        assert meet
        assert all(a.cells[i].status == "inhabited" for i in meet)
