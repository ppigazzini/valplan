"""Tool programs: straight-line calls, runtime type tests that branch, and a returned value.

A program is what the planner emits and what the verifier and the runner read. A call
binds each argument to a variable already held; its guaranteed result fields become
variables named ``<label>.<field>``. A test asks whether a variable lies in a named set
-- a tool argument's schema or the goal -- and both branches continue with the variable
narrowed. Every path ends in a return.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Call:
    """Call ``tool`` with each argument bound to a variable."""

    label: str
    tool: str
    args: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Test:
    """Branch on whether ``var`` lies in the set ``against`` names.

    ``against`` is ``"<tool>.<arg>"`` for an argument's schema, or ``"goal"``.
    """

    #: Not a test case, whatever pytest's name-based collection assumes.
    __test__ = False

    var: str
    against: str
    then: Program
    other: Program


@dataclass(frozen=True, slots=True)
class Return:
    """End the path with ``var`` as the answer."""

    var: str


@dataclass(frozen=True, slots=True)
class Stop:
    """End a path the contracts give no way through: a weak program's uncovered case.

    ``var`` is the variable whose narrowed type no tool and no goal accepts, which is what
    the path's tests have established about the value that reaches it.
    """

    var: str


type Step = Call | Test | Return | Stop
type Program = tuple[Step, ...]


def to_json(program: Program) -> list[dict[str, Any]]:
    """Serialise a program."""
    out: list[dict[str, Any]] = []
    for step in program:
        match step:
            case Call(label, tool, args):
                out.append({"call": tool, "as": label, "args": dict(args)})
            case Test(var, against, then, other):
                out.append(
                    {"if": var, "in": against, "then": to_json(then), "else": to_json(other)}
                )
            case Return(var):
                out.append({"return": var})
            case Stop(var):
                out.append({"stop": var})
    return out


class ShapeError(ValueError):
    """A program whose structure no path can be read from: a step after a branch or an end."""


def check_shape(program: Program) -> None:
    """Raise unless every block ends in exactly one test, return or stop, and nothing follows.

    A step after a test would never run, and a block that ends in a call never answers; a
    reader that skipped either would report a program correct that does not mean what it
    says.
    """
    for i, step in enumerate(program):
        last = i == len(program) - 1
        match step:
            case Test(_, _, then, other):
                if not last:
                    msg = f"step {i + 1} follows a test"
                    raise ShapeError(msg)
                check_shape(then)
                check_shape(other)
            case Return() | Stop():
                if not last:
                    msg = f"step {i + 1} follows an end"
                    raise ShapeError(msg)
            case Call():
                if last:
                    msg = "the block ends in a call, not in a return, a stop or a test"
                    raise ShapeError(msg)
    if not program:
        msg = "an empty block"
        raise ShapeError(msg)


def from_json(steps: list[dict[str, Any]]) -> Program:
    """Read a program serialised by `to_json`, or written by hand or by a model.

    The structure is checked (`check_shape`); the types are the verifier's to check.
    """
    program = _read(steps)
    check_shape(program)
    return program


def _read(steps: list[dict[str, Any]]) -> Program:
    out: list[Step] = []
    for step in steps:
        if "call" in step:
            out.append(Call(step["as"], step["call"], tuple(step["args"].items())))
        elif "if" in step:
            then, other = _read(step["then"]), _read(step["else"])
            out.append(Test(step["if"], step["in"], then, other))
        elif "return" in step:
            out.append(Return(step["return"]))
        elif "stop" in step:
            out.append(Stop(step["stop"]))
        else:
            msg = f"unknown step {json.dumps(step)}"
            raise ValueError(msg)
    return tuple(out)


def render(program: Program, indent: int = 0) -> str:
    """Render a program as indented pseudocode."""
    return "\n".join(_lines(program, indent))


def _lines(program: Program, indent: int) -> Iterator[str]:
    pad = "    " * indent
    for step in program:
        match step:
            case Call(label, tool, args):
                bound = ", ".join(f"{a}={v}" for a, v in args)
                yield f"{pad}{label} = {tool}({bound})"
            case Test(var, against, then, other):
                yield f"{pad}if {var} in {against}:"
                yield from _lines(then, indent + 1)
                yield f"{pad}else:"
                yield from _lines(other, indent + 1)
            case Return(var):
                yield f"{pad}return {var}"
            case Stop(var):
                yield f"{pad}stop  # {var} is not covered by this program"


def calls(program: Program) -> int:
    """Return the number of calls on the longest path."""
    longest = 0
    count = 0
    for step in program:
        match step:
            case Call():
                count += 1
            case Test(_, _, then, other):
                return max(longest, count + max(calls(then), calls(other)))
            case Return() | Stop():
                pass
    return max(longest, count)


def stops(program: Program) -> int:
    """Return the number of uncovered paths."""
    total = 0
    for step in program:
        match step:
            case Test(_, _, then, other):
                total += stops(then) + stops(other)
            case Stop():
                total += 1
            case Call() | Return():
                pass
    return total


def uses(program: Program) -> set[str]:
    """Return every variable a step of ``program`` reads, on any path."""
    out: set[str] = set()
    for step in program:
        match step:
            case Call(_, _, args):
                out.update(v for _, v in args)
            case Test(var, _, then, other):
                out.add(var)
                out |= uses(then) | uses(other)
            case Return(var) | Stop(var):
                out.add(var)
    return out


def prune(program: Program) -> Program:
    """Drop every call no later step on its path reads a result of, then renumber once.

    The search makes a call when it fits the depth it has left, and a branch with depth to
    spare can carry one nothing uses. Removing it changes no type a later step sees.

    The renumbering runs once, over the whole program. Renumbering each branch on its own
    would restart at ``c1`` inside a branch whose path already holds a ``c1``, and a read
    of the outer variable would then name the inner one.
    """
    return relabel(_prune(program))


def _prune(program: Program) -> Program:
    out: list[Step] = []
    for i, step in enumerate(program):
        match step:
            case Call(label, _, _):
                later = uses(program[i + 1 :])
                if any(v.startswith(f"{label}.") for v in later):
                    out.append(step)
            case Test(var, against, then, other):
                out.append(Test(var, against, _prune(then), _prune(other)))
            case _:
                out.append(step)
    return tuple(out)


def relabel(program: Program, start: int = 0, names: dict[str, str] | None = None) -> Program:
    """Renumber the calls of each path ``c1``, ``c2``, ... in order, rewriting every read."""
    names = dict(names or {})

    def ref(var: str) -> str:
        label, dot, rest = var.partition(".")
        return f"{names[label]}.{rest}" if dot and label in names else var

    out: list[Step] = []
    n = start
    for step in program:
        match step:
            case Call(label, tool, args):
                n += 1
                bound = tuple((a, ref(v)) for a, v in args)
                names[label] = f"c{n}"
                out.append(Call(f"c{n}", tool, bound))
            case Test(var, against, then, other):
                out.append(
                    Test(ref(var), against, relabel(then, n, names), relabel(other, n, names))
                )
            case Return(var):
                out.append(Return(ref(var)))
            case Stop(var):
                out.append(Stop(ref(var)))
    return tuple(out)


def sink(program: Program) -> Program:
    """Move each call into the one branch of a later test that reads its results.

    A tool call can act on the world, so a path should not make a call it does not need: a
    weak program that opens a ticket and then stops has done half a job. A call whose
    results only one branch of the block's test reads moves to the start of that branch;
    a call both branches read, or the test itself reads, stays. Calls are tried from the
    last to the first, so a call that a moved call reads can follow it into the branch.
    """
    return relabel(_sink(program))


def _sink(program: Program) -> Program:
    if not program or not isinstance(program[-1], Test):
        return program
    test = program[-1]
    then, other = _sink(test.then), _sink(test.other)
    kept = list(program[:-1])
    for i in range(len(kept) - 1, -1, -1):
        step = kept[i]
        if not isinstance(step, Call):
            continue
        mine = f"{step.label}."
        later = uses(tuple(kept[i + 1 :]))
        if test.var.startswith(mine) or any(v.startswith(mine) for v in later):
            continue
        in_then = any(v.startswith(mine) for v in uses(then))
        in_other = any(v.startswith(mine) for v in uses(other))
        if in_then == in_other:
            continue
        del kept[i]
        if in_then:
            then = (step, *then)
        else:
            other = (step, *other)
    return (*kept, Test(test.var, test.against, then, other))
