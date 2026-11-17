"""Verify a tool program with valgebra-planning's verifier: valgebra alone, without the cells.

The verifier is valgebra-planning's (`valplan/_planning.py`): it carries each reference's exact
set, asks valgebra for every inclusion, and reports valgebra's own three-valued answer. It reads
neither the cells nor the search here, so it checks the planning; it shares the contract reader
and valgebra with the planner, and checks neither of those. A program the planner emits must
verify; a program from anywhere else, written by hand or proposed by a language model, is
checked the same way.

A program here is written in valgebra-planning's language to be verified: a call is a call
whose result is named by its label, a test a branch on a tool's argument, a return and a stop
the same. A test against the goal has no form there, so a program holding one is refused by a
check saying so; the planner emits none. A program naming a tool, an argument or a variable it
does not have is refused by a check naming it, never by an exception. A refuted link comes with
a value of the variable outside the argument when one of the example values given is one.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from valplan import _planning as planning
from valplan.contracts import Task, Tool
from valplan.program import Call, Program, Return, ShapeError, Stop, Test, check_shape

#: valgebra-planning's verdict on a link, as valgebra's relation names it here.
RELATION = {"proven": "subset", "refuted": "not_subset", "undecided": "undecided"}


@dataclass(frozen=True, slots=True)
class Check:
    """One inclusion the program depends on, and valgebra's answer to it."""

    path: str
    claim: str
    relation: str
    #: A value inside the left side and outside the right, for a refuted inclusion.
    example: Any = field(default=None, compare=False)

    @property
    def holds(self) -> bool:
        """Return whether valgebra proved the inclusion."""
        return self.relation == "subset"


def verify(
    tools: Sequence[Tool], task: Task, program: Program, examples: Iterable[Any] = ()
) -> list[Check]:
    """Return every check along every path of ``program``.

    ``examples`` are candidate values, such as `valplan.synth.witnesses` draws; the verifier
    tries them first, in search of a value refuting a link.
    """
    try:
        check_shape(program)
    except ShapeError as exc:
        return [Check("", f"well-formed program: {exc}", "not_subset")]
    by_name = {t.name: t for t in tools}
    refused = _refused(program, by_name, {s.name for s in task.inputs}, "")
    if refused is not None:
        return [refused]
    contracts = {t.name: t.contract for t in tools if t.contract is not None}
    inputs = {s.name: s.source for s in task.inputs}
    read = planning.read_task(task.name, inputs, task.goal_source)
    drawn = tuple(examples)
    named = _Names(by_name, frozenset(inputs))
    found = planning.verify(
        named.block(program), contracts, read, examples=dict.fromkeys(named.refs(program), drawn)
    )
    checks = [
        Check(link.where, link.claim, RELATION[link.verdict], next(iter(link.counterexample), None))
        for link in found.links
    ]
    checks += [
        Check(gap.where, f"the path stops with {gap.ref} uncovered", "uncovered")
        for gap in found.gaps
    ]
    return checks


def _refused(program: Program, tools: Mapping[str, Tool], bound: set[str], at: str) -> Check | None:
    """Return the check refusing the first name ``program`` uses and does not have, if any."""
    bound = set(bound)
    for i, step in enumerate(program):
        here = f"{at}{i}"
        claim = _problem(step, tools, bound)
        if claim is not None:
            return Check(here, claim, "not_subset")
        match step:
            case Call(label, name, _):
                bound |= {f"{label}.{r.name}" for r in tools[name].results}
            case Test(_, _, then, other):
                return _refused(then, tools, bound, f"{here}.then.") or _refused(
                    other, tools, bound, f"{here}.else."
                )
            case _:
                return None
    return None


def _problem(step: object, tools: Mapping[str, Tool], bound: set[str]) -> str | None:
    """Return what ``step`` names and does not have: a tool, an argument, a bound variable."""
    claim = None
    match step:
        case Call(_, name, args):
            if name not in tools:
                claim = f"tool {name} exists"
            else:
                taken = {s.name for s in tools[name].args}
                claim = next(
                    (
                        f"{var} is bound before {name}"
                        if var not in bound
                        else f"{name} takes {arg}"
                        for arg, var in args
                        if var not in bound or arg not in taken
                    ),
                    None,
                )
        case Test(var, against, _, _):
            if var not in bound:
                claim = f"{var} is bound before its test"
            elif against == "goal":
                claim = "a test against the goal, which valgebra-planning's language lacks"
            elif _argument(against, tools) is None:
                claim = f"{against} names an argument of a tool"
        case Return(var) | Stop(var):
            if var not in bound:
                claim = f"{var} is bound before return"
    return claim


def _argument(against: str, tools: Mapping[str, Tool]) -> tuple[str, str] | None:
    """Return the tool and the argument ``tool.argument`` names, a tool's name holding dots."""
    for name, tool in tools.items():
        arg = against.removeprefix(f"{name}.")
        if arg != against and arg in {s.name for s in tool.args}:
            return name, arg
    return None


@dataclass(frozen=True, slots=True)
class _Names:
    """A program's names, as valgebra-planning's language writes them."""

    tools: Mapping[str, Tool]
    inputs: frozenset[str]

    def ref(self, var: str) -> planning.Ref:
        """Return a variable as a reference: ``c1.customer.id`` is ``c1`` at ``customer.id``."""
        if var in self.inputs:
            return planning.Ref(var)
        head, *path = var.split(".")
        return planning.Ref(head, tuple(p for p in path if p != "$"))

    def block(self, program: Program) -> planning.Block:
        """Return ``program`` in valgebra-planning's language; `_refused` has passed it."""
        calls: list[planning.Call] = []
        for step in program:
            match step:
                case Call(label, tool, args):
                    bindings = tuple((arg, self.ref(var)) for arg, var in args)
                    calls.append(planning.Call(tool, bindings, label))
                case Test(var, against, then, other):
                    tool, arg = _argument(against, self.tools) or ("", "")
                    end = planning.Branch(
                        self.ref(var), tool, arg, self.block(then), self.block(other)
                    )
                    return planning.Block(tuple(calls), end)
                case Return(var):
                    return planning.Block(tuple(calls), planning.Return(self.ref(var)))
                case Stop(var):
                    return planning.Block(tuple(calls), planning.Stop(self.ref(var)))
        msg = "a path ends in no return"
        raise ShapeError(msg)

    def refs(self, program: Program) -> set[str]:
        """Return every variable ``program`` reads, as valgebra-planning writes it."""
        found: set[str] = set()
        for step in program:
            match step:
                case Call(_, _, args):
                    found |= {str(self.ref(var)) for _, var in args}
                case Test(var, _, then, other):
                    found |= {str(self.ref(var))} | self.refs(then) | self.refs(other)
                case Return(var) | Stop(var):
                    found.add(str(self.ref(var)))
        return found
