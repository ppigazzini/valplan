"""Verify a tool program against the contracts, directly with valgebra and without cells.

The verifier shares no code path with the planner's abstraction: it carries each
variable's exact set, asks valgebra for every inclusion, and reports valgebra's own
three-valued answer. A program the planner emits must verify; a program from anywhere else
-- written by hand, or proposed by a language model -- is checked the same way, and a
broken link is reported as refuted (``not_subset``: a value of the variable is outside the
argument) or as undecided.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from valgebra import Validator, complement, intersection

from valplan.contracts import Task, Tool
from valplan.program import Call, Program, Return, ShapeError, Stop, Test, check_shape
from valplan.synth import slot_named


@dataclass(frozen=True, slots=True)
class Check:
    """One inclusion the program depends on, and valgebra's answer to it."""

    path: str
    claim: str
    relation: str

    @property
    def holds(self) -> bool:
        """Return whether valgebra proved the inclusion."""
        return self.relation == "subset"


def verify(tools: Sequence[Tool], task: Task, program: Program) -> list[Check]:
    """Return every check along every path of ``program``."""
    try:
        check_shape(program)
    except ShapeError as exc:
        return [Check("", f"well-formed program: {exc}", "not_subset")]
    by_name = {t.name: t for t in tools}
    env = {s.name: s.schema for s in task.inputs}
    out: list[Check] = []
    _walk(by_name, tools, task, program, env, "", out)
    return out


def _walk(
    by_name: dict[str, Tool],
    tools: Sequence[Tool],
    task: Task,
    program: Program,
    env: dict[str, Validator[Any]],
    path: str,
    out: list[Check],
) -> None:
    env = dict(env)
    for i, step in enumerate(program):
        at = f"{path}{i}"
        match step:
            case Call(label, name, args):
                tool = by_name.get(name)
                if tool is None:
                    out.append(Check(at, f"tool {name} exists", "not_subset"))
                    return
                for arg, var in args:
                    if var not in env:
                        out.append(Check(at, f"{var} is bound before {name}", "not_subset"))
                        return
                    try:
                        slot = tool.arg(arg)
                    except KeyError:
                        out.append(Check(at, f"{name} takes {arg}", "not_subset"))
                        return
                    rel = env[var].relation_to(slot.schema)
                    out.append(Check(at, f"{var} <= {name}.{arg}", rel))
                record = Validator({a: env[v] for a, v in args})
                rel = record.relation_to(tool.input)
                out.append(Check(at, f"arguments <= {name} input", rel))
                for r in tool.results:
                    env[f"{label}.{r.name}"] = r.schema
            case Test(var, against, then, other):
                target = task.goal if against == "goal" else slot_named(tools, against).schema
                yes = dict(env, **{var: intersection(env[var], target)})
                no = dict(env, **{var: intersection(env[var], complement(target))})
                _walk(by_name, tools, task, then, yes, f"{at}.then.", out)
                _walk(by_name, tools, task, other, no, f"{at}.else.", out)
                return
            case Stop(var):
                out.append(Check(at, f"{var} is covered by some contract", "uncovered"))
                return
            case Return(var):
                if var not in env:
                    out.append(Check(at, f"{var} is bound before return", "not_subset"))
                    return
                out.append(Check(at, f"{var} <= goal", env[var].relation_to(task.goal)))
                return
    out.append(Check(f"{path}end", "path ends in a return", "not_subset"))
