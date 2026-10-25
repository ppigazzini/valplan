"""Verify a tool program against the contracts, directly with valgebra and without cells.

The verifier is independent of the abstraction and the search: it carries each
variable's exact set, asks valgebra for every inclusion, and reports valgebra's own
three-valued answer. It shares the compiler and valgebra with the planner, so it checks
the planning, not those two. A program the planner emits must verify; a program from
anywhere else -- written by hand, or proposed by a language model -- is checked the same
way. A refuted link (``not_subset``) comes with a value of the variable outside the
argument when one of the example values given is such a value; an ill-formed program
gets a check that says so, never an exception.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from valplan._valgebra import Validator, complement, intersection
from valplan.contracts import Task, Tool
from valplan.program import Call, Program, Return, ShapeError, Stop, Test, check_shape
from valplan.synth import slot_named


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

    ``examples`` are candidate values, such as `valplan.synth.witnesses` draws; the first
    one inside a refuted inclusion's left side and outside its right side is attached.
    """
    try:
        check_shape(program)
    except ShapeError as exc:
        return [Check("", f"well-formed program: {exc}", "not_subset")]
    walk = _Walk({t.name: t for t in tools}, tools, task, list(examples))
    walk.run(program, {s.name: s.schema for s in task.inputs}, "")
    return walk.out


@dataclass(slots=True)
class _Walk:
    by_name: dict[str, Tool]
    tools: Sequence[Tool]
    task: Task
    examples: list[Any]
    out: list[Check] = field(default_factory=list)

    def check(self, at: str, claim: str, left: Validator[Any], right: Validator[Any]) -> None:
        relation = left.relation_to(right)
        example = None
        if relation == "not_subset":
            example = next(
                (w for w in self.examples if left.is_valid(w) and not right.is_valid(w)), None
            )
        self.out.append(Check(at, claim, relation, example))

    def fail(self, at: str, claim: str) -> None:
        self.out.append(Check(at, claim, "not_subset"))

    def run(self, program: Program, env: dict[str, Validator[Any]], path: str) -> None:
        env = dict(env)
        for i, step in enumerate(program):
            at = f"{path}{i}"
            match step:
                case Call():
                    if not self.call(step, env, at):
                        return
                case Test():
                    self.test(step, env, at)
                    return
                case Stop(var):
                    self.out.append(Check(at, f"the path stops with {var} uncovered", "uncovered"))
                    return
                case Return(var):
                    if var not in env:
                        self.fail(at, f"{var} is bound before return")
                    else:
                        self.check(at, f"{var} <= goal", env[var], self.task.goal)
                    return
        self.fail(f"{path}end", "path ends in a return")

    def call(self, step: Call, env: dict[str, Validator[Any]], at: str) -> bool:
        """Check one call and bind its results; return whether the path can go on."""
        tool = self.by_name.get(step.tool)
        if tool is None:
            self.fail(at, f"tool {step.tool} exists")
            return False
        for arg, var in step.args:
            if var not in env:
                self.fail(at, f"{var} is bound before {step.tool}")
                return False
            if arg not in {s.name for s in tool.args}:
                self.fail(at, f"{step.tool} takes {arg}")
                return False
            self.check(at, f"{var} <= {step.tool}.{arg}", env[var], tool.arg(arg).schema)
        record = Validator({a: env[v] for a, v in step.args})
        self.check(at, f"arguments <= {step.tool} input", record, tool.input)
        for r in tool.results:
            env[f"{step.label}.{r.name}"] = r.schema
        return True

    def test(self, step: Test, env: dict[str, Validator[Any]], at: str) -> None:
        """Walk both branches of a test with the variable narrowed in each."""
        if step.var not in env:
            self.fail(at, f"{step.var} is bound before its test")
            return
        if step.against == "goal":
            target = self.task.goal
        else:
            try:
                target = slot_named(self.tools, step.against).schema
            except KeyError:
                self.fail(at, f"{step.against} names an argument of a tool")
                return
        value = env[step.var]
        self.run(step.then, env | {step.var: intersection(value, target)}, f"{at}.then.")
        self.run(
            step.other, env | {step.var: intersection(value, complement(target))}, f"{at}.else."
        )
