import runpy
from pathlib import Path
from typing import Annotated, Literal

import pytest
from annotated_types import Ge, Le
from typing_extensions import TypedDict
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
            ("plain_return", "TypedDict"),
        ],
    )
    def test_it_refuses_what_is_not_a_json_contract(self, fn, reason):
        def takes_tuple(x: tuple[int, int]) -> None:
            del x

        def takes_open(x: Open) -> None:
            del x

        def star(*xs: int) -> None:
            del xs

        def plain_return(x: int) -> int:
            return x

        named = {
            "tuple": takes_tuple,
            "open": takes_open,
            "star": star,
            "plain_return": plain_return,
        }
        with pytest.raises(Unsupported, match=reason):
            python_tool(named.get(fn, fn) if isinstance(fn, str) else fn, name="t")


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
