import runpy
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, Literal, NotRequired, TypedDict

import pytest
from annotated_types import Ge, Le
from valgebra import Regex

from valplan.native import native_values, python_impl, python_task, python_tool
from valplan.program import stops
from valplan.run import run
from valplan.schema import Unsupported
from valplan.synth import Planner, witnesses
from valplan.verify import verify

EXAMPLE = Path(__file__).parent.parent / "examples" / "python" / "helpdesk.py"
Country = Annotated[str, Regex(r"[A-Z]{2}")]


class Rate(TypedDict, closed=True):
    rate_percent: Annotated[float, Ge(0), Le(30)]


class Open(TypedDict):
    x: int


class Tier(StrEnum):
    PRO = "pro"


class Level(IntEnum):
    ONE = 1


class Page[T](TypedDict, closed=True):
    items: list[T]
    first: T
    cursor: NotRequired[str]


class Pair[A, B = Country](TypedDict, closed=True):
    left: A
    right: B


class LevelPage[T](TypedDict, closed=True):
    items: list[T]
    level: Level


class RatePair(Pair[Rate]):
    pass


def vat_anywhere(country: Country) -> Rate:
    """Return a VAT rate for any country."""
    return Rate(rate_percent=20.0 if country != "US" else 0.0)


class TestReading:
    def test_parameters_are_arguments_and_the_typeddict_gives_the_results(self):
        def f(a: int, b: Literal["x", "y"] = "x") -> Rate:
            del b
            return Rate(rate_percent=float(a))

        t = python_tool(f)
        assert [(s.name, s.required) for s in t.args] == [("a", True), ("b", False)]
        assert [r.name for r in t.results] == ["rate_percent"]
        assert t.plain
        assert t.input.is_valid({"a": 1})
        assert not t.input.is_valid({"a": 1, "c": 2})

    def test_a_function_returning_no_typeddict_has_its_whole_result_as_one_slot(self):
        def double(x: int) -> int:
            return 2 * x

        t = python_tool(double)
        assert [(r.name, r.path) for r in t.results] == [("$", ())]
        assert t.output.is_valid(4)

    def test_an_open_typeddict_result_is_refused(self):
        def f() -> Open:
            return Open(x=1)

        with pytest.raises(Unsupported, match="not JSON values"):
            python_tool(f)

    def test_a_function_returning_nothing_has_no_results(self):
        def ping(host: str) -> None:
            del host

        assert python_tool(ping).results == ()

    @pytest.mark.parametrize(
        ("fn", "reason"),
        [
            (lambda x: x, "no annotation"),
            ("tuple", "not JSON values"),
            ("open", "not JSON values"),
            ("star", "by keyword"),
            ("strenum", "no JSON value is a Tier"),
            ("intenum", "no JSON value is a Level"),
            ("enum_literal", "is a Tier, no JSON value"),
        ],
    )
    def test_it_refuses_what_is_not_a_json_contract(self, fn, reason):
        def takes_tuple(x: tuple[int, int]) -> None:
            del x

        def takes_open(x: Open) -> None:
            del x

        def star(*xs: int) -> None:
            del xs

        def strenum(x: Tier) -> None:
            del x

        def intenum(x: Level) -> None:
            del x

        def enum_literal(x: Literal[Tier.PRO]) -> None:
            del x

        named = {
            "tuple": takes_tuple,
            "open": takes_open,
            "star": star,
            "strenum": strenum,
            "intenum": intenum,
            "enum_literal": enum_literal,
        }
        with pytest.raises(Unsupported, match=reason):
            python_tool(named.get(fn, fn) if isinstance(fn, str) else fn, name="t")


class TestGenericRecords:
    def test_an_applied_typeddict_gives_its_keys_with_the_argument_in_place(self):
        def page(country: Country) -> Page[Country]:
            return Page(items=[country], first=country)

        t = python_tool(page)
        results = {s.name: s.schema for s in t.results}
        assert list(results) == ["items", "first"]
        assert results["first"].is_valid("FR")
        assert not results["first"].is_valid("fr")
        assert results["items"].is_valid(["FR", "DE"])
        assert t.output.is_valid({"items": ["FR"], "first": "FR", "cursor": "c"})

    def test_a_typeddict_deriving_from_an_applied_one_reads_its_fields_bound(self):
        def pair() -> RatePair:
            return RatePair(left=Rate(rate_percent=1.0), right="FR")

        results = {s.name: s.schema for s in python_tool(pair).results}
        assert results["left"].is_valid({"rate_percent": 20.0})
        assert not results["left"].is_valid({"rate_percent": 31.0})
        assert results["right"].is_valid("FR")

    def test_a_parameter_left_out_takes_its_default(self):
        def pair() -> Pair[int]:
            return Pair(left=1, right="FR")

        results = {s.name: s.schema for s in python_tool(pair).results}
        assert results["right"].is_valid("FR")
        assert not results["right"].is_valid("fr")

    def test_an_applied_typeddict_is_held_to_json_classes_in_every_field(self):
        def levels(x: LevelPage[int]) -> None:
            del x

        with pytest.raises(Unsupported, match="no JSON value is a Level"):
            python_tool(levels)

    def test_a_task_takes_an_applied_typeddict_of_inputs(self):
        task = python_task("t", Pair[int], Rate)
        assert [(s.name, s.schema.is_valid("FR")) for s in task.inputs] == [
            ("left", False),
            ("right", True),
        ]


class TestFiniteValues:
    def test_python_equality_is_kept(self):
        assert native_values(Literal[1, "a"]) == [1, "a"]
        assert native_values(bool) == [True, False]
        assert native_values(Literal["a"] | None) == ["a", None]
        assert native_values(int) is None

    def test_an_annotated_literal_keeps_the_values_its_markers_admit(self):
        assert native_values(Annotated[Literal[1, 5, 9], Ge(4)]) == [5, 9]


def test_a_task_takes_a_typeddict_of_inputs():
    class Inputs(TypedDict):
        country: Country

    task = python_task("t", Inputs, Rate.__annotations__["rate_percent"])
    assert [s.name for s in task.inputs] == ["country"]


def test_both_doors_plan_together(library, tasks):
    task = tasks["vat-for-customer"]
    mixed = [*library, python_tool(vat_anywhere)]
    planner = Planner(mixed, task, witnesses(mixed, task))
    program = planner.plan(max_depth=6, weak=True)
    assert program is not None
    assert stops(program) == 0
    assert all(c.holds or c.relation == "undecided" for c in verify(mixed, task, program))


def test_a_program_runs_on_the_python_functions_themselves():
    task = python_task("t", {"country": Country}, Annotated[float, Ge(0), Le(30)])
    tool = python_tool(vat_anywhere)
    program = Planner([tool], task).plan(max_depth=3)
    assert program is not None
    assert (
        run([tool], task, program, {"country": "IT"}, {"vat_anywhere": python_impl(vat_anywhere)})
        == 20.0
    )


def test_the_example_plans_verifies_and_runs(capsys):
    runpy.run_path(str(EXAMPLE), run_name="__main__")
    out = capsys.readouterr().out
    assert "uncovered: c1.tier in {'free', 'pro'}" in out
    assert "run on an enterprise customer: ESC-" in out
