import random

from valgebra import intersection

from valplan.abstraction import Abstraction
from valplan.contracts import tool
from valplan.sample import Sampler
from valplan.schema import compile_schema, finite
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


class TestUnions:
    def test_a_union_meets_only_the_kinds_its_branches_meet(self):
        ga = {"type": "string", "pattern": "^ga_[a-z0-9]{6}$"}
        gb = {"type": "string", "pattern": "^gb_[a-z0-9]{6}$"}
        preds = [compile_schema(s) for s in (ga, gb, {"anyOf": [ga, gb]}, {"type": "integer"})]
        a = Abstraction(preds, unions={preds[2]: [preds[0], preds[1]]})
        inside_union = [c for c in a.cells if 2 in c.inside]
        assert {c.kind for c in inside_union} == {"string"}
        assert all(c.inside & {0, 1} for c in inside_union)


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


def test_cells_past_valgebras_definition_limit_are_kept_not_raised():
    # A cell outside 130 recursive schemas meets 130 definitions; valgebra builds 128.
    def tree(i):
        kids = {"type": "array", "items": {"$ref": "#/$defs/node"}}
        node = {
            "type": "object",
            "properties": {"tag": {"const": f"t{i}"}, "kids": kids},
            "required": ["tag"],
        }
        return {"$defs": {"node": node}, "$ref": "#/$defs/node"}

    a = Abstraction([compile_schema(tree(i)) for i in range(130)])
    outside = [c for c in a.cells if c.kind == "object" and not c.inside]
    assert len(outside) == 1
    assert outside[0].status == "inhabited"
