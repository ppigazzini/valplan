"""Synthesise tool programs that are well-typed on every path, by search over cells.

The state is the set of variables the agent holds, each typed by the cells it may lie in.
A call is enabled when each required argument can be bound to a variable whose cells all
lie inside the argument's schema, and the assembled argument object is proven inside the
tool's whole input schema. A call adds its guaranteed result fields as new variables.

Where a variable only overlaps an argument's schema, the program can test it at run time:
the *then* branch continues with the variable narrowed to the overlap, the *else* branch
with the rest, and the program is accepted only if both branches reach the goal. That is
strong planning under the nondeterminism of tool outputs (Cimatti, Pistore, Roveri and
Traverso 2003), with the outcomes partitioned by the abstraction rather than enumerated.

The search deepens iteratively on the number of calls and tests along a path, so the
first program found is a shallowest one.

Where no strong program exists, a *weak* one is the diagnosis: the same search, letting
the *else* branch of a test stop when its *then* branch succeeds. Each stop names the
variable and, through the tests above it, the exact set of values no contract covers.
"""

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from valplan._valgebra import Validator, complement, intersection
from valplan.abstraction import Abstraction, Cells, SoundnessError
from valplan.contracts import Slot, Task, Tool
from valplan.native import is_native, native_values
from valplan.program import Call, Program, Return, Step, Stop, Test, prune, sink, stops
from valplan.sample import Sampler
from valplan.schema import Compiler, branches, finite, interval


@dataclass(frozen=True, slots=True)
class Var:
    """A variable the agent holds: its name, its cells, and its exact set."""

    name: str
    cells: Cells
    schema: Validator[Any] = field(compare=False, repr=False)


#: How many bindings of one call to try before giving up on it: argument choices
#: multiply, and every one costs an inclusion check on the whole input schema.
MAX_BINDINGS = 16


class Planner:
    """Plan for one task over one tool library."""

    def __init__(self, tools: Sequence[Tool], task: Task, witnesses: Iterable[Any] = ()) -> None:
        self.tools = sorted(tools, key=lambda t: t.name)
        self.task = task
        named = list(task.inputs) + [s for t in self.tools for s in t.args + t.results]
        predicates = [s.schema for s in named] + [task.goal]
        listed = {s.schema: v for s in named if (v := _listed(s.source, s.root)) is not None}
        goal_values = _listed(task.goal_source, None)
        if goal_values is not None:
            listed[task.goal] = goal_values
        # A range profile is a JSON Schema reading -- an integer there is a value, whatever
        # its spelling -- so a Python annotation, where `int` excludes 1.0, gets none and
        # its cells are left to valgebra, which decides plain `int` ranges.
        ranges = {
            s.schema: r
            for s in named
            if not is_native(s.source) and (r := interval(s.source)) is not None
        }
        goal_range = None if is_native(task.goal_source) else interval(task.goal_source)
        if goal_range is not None:
            ranges[task.goal] = goal_range
        sources = [(s.schema, s.source, s.root) for s in named]
        sources.append((task.goal, task.goal_source, None))
        unions: dict[Validator[Any], list[Validator[Any]]] = {}
        for schema, source, root in sources:
            parts = None if is_native(source) else branches(source)
            if parts is None:
                continue
            compiler = Compiler(source if root is None else root)
            unions[schema] = [compiler.compile(b) for b in parts]
            # A branch's range lets the interval rule read the union as ranges.
            ranges |= {
                v: r for v, b in zip(unions[schema], parts, strict=True) if (r := interval(b))
            }
        self.abstraction = Abstraction(predicates, witnesses, listed, ranges, unions)
        self.goal = self.abstraction.cells_of(task.goal)
        self._whole: dict[tuple[str, tuple[Validator[Any], ...]], bool] = {}
        self._failed: set[tuple[frozenset[Cells], int, bool]] = set()
        self.expanded = 0
        self.weak = False

    def initial(self) -> tuple[Var, ...]:
        """Return the task inputs as variables."""
        return tuple(
            Var(s.name, self.abstraction.cells_of(s.schema), s.schema) for s in self.task.inputs
        )

    def plan(self, max_depth: int = 6, *, weak: bool = False) -> Program | None:
        """Return a shallowest program reaching the goal on every path, or None.

        With ``weak``, fall back to a shallowest program that reaches it on some path and
        stops on the others; `weak` then records that the fallback was taken.
        """
        start = self.initial()
        for allow in (False, True) if weak else (False,):
            for depth in range(max_depth + 1):
                found = self._solve(start, depth, 0, allow)
                if found is not None:
                    if allow:
                        found = self._extend(found, start, max_depth, 0, 0)
                    program = sink(prune(found))
                    self.weak = stops(program) > 0
                    self._recheck(program, {v.name: v.cells for v in start})
                    return program
        return None

    def _extend(
        self, program: Program, held: tuple[Var, ...], budget: int, used: int, made: int
    ) -> Program:
        """Replace each stop of a weak program by a continuation, where one fits the budget.

        The shallowest weak program stops wherever its own depth ran out, and a deeper
        continuation may cover what reaches that stop. Each stop gets its own search, from
        the variables held there, within the depth the path has left.
        """
        out: list[Step] = []
        by_name = {t.name: t for t in self.tools}
        for step in program:
            match step:
                case Call(label, name, _):
                    tool = by_name[name]
                    held = held + tuple(
                        Var(f"{label}.{r.name}", self.abstraction.cells_of(r.schema), r.schema)
                        for r in tool.results
                    )
                    used += 1
                    made = max(made, int(label[1:]))
                    out.append(step)
                case Test(var, against, then, other):
                    slot = slot_named(self.tools, against)
                    inside = self.abstraction.cells_of(slot.schema)
                    v = next(h for h in held if h.name == var)
                    yes = Var(var, v.cells & inside, intersection(v.schema, slot.schema))
                    no = Var(var, v.cells - inside, intersection(v.schema, complement(slot.schema)))
                    then = self._extend(then, self._replace(held, yes), budget, used + 1, made)
                    other = self._extend(other, self._replace(held, no), budget, used + 1, made)
                    out.append(Test(var, against, then, other))
                    return tuple(out)
                case Stop(var):
                    rest = self._continuation(held, var, budget - used, made)
                    return (*out, *(rest or (step,)))
                case Return():
                    out.append(step)
                    return tuple(out)
        return tuple(out)

    def _continuation(
        self, held: tuple[Var, ...], var: str, budget: int, made: int
    ) -> Program | None:
        """Return a shallowest continuation from a stop, strong if one fits, else narrowing.

        A weak continuation is accepted only if its first test is on the stopped variable:
        one that tests something else covers values of the stopped case only where an
        unrelated input happens to look like an argument -- a subject line that reads
        "enterprise" -- and is no progress.
        """
        for depth in range(1, budget + 1):
            rest = self._solve(held, depth, made, weak=False)
            if rest is not None:
                return rest
        for depth in range(1, budget + 1):
            rest = self._solve(held, depth, made, weak=True)
            first = next((s for s in rest or () if isinstance(s, Test)), None)
            if first is not None and first.var == var:
                return rest
        return None

    def _recheck(self, program: Program, held: dict[str, Cells]) -> None:
        """Raise unless every binding and return of ``program`` holds over the cells.

        The search builds programs that hold by construction; the post-processing that
        prunes and renumbers them does not, so the program returned is checked again here.
        """
        a = self.abstraction
        by_name = {t.name: t for t in self.tools}
        held = dict(held)
        for step in program:
            match step:
                case Call(label, name, args):
                    tool = by_name[name]
                    for arg, var in args:
                        if var not in held or not held[var] <= a.cells_of(tool.arg(arg).schema):
                            msg = f"{name}.{arg} bound to {var} outside it"
                            raise SoundnessError(msg)
                    for r in tool.results:
                        held[f"{label}.{r.name}"] = a.cells_of(r.schema)
                case Test(var, against, then, other):
                    inside = a.cells_of(slot_named(self.tools, against).schema)
                    self._recheck(then, held | {var: held[var] & inside})
                    self._recheck(other, held | {var: held[var] - inside})
                    return
                case Return(var):
                    if not held[var] <= self.goal:
                        msg = f"return of {var} outside the goal"
                        raise SoundnessError(msg)
                case Stop():
                    return

    def _solve(self, held: tuple[Var, ...], depth: int, made: int, weak: bool) -> Program | None:  # noqa: FBT001
        self.expanded += 1
        for v in held:
            if v.cells <= self.goal:
                return (Return(v.name),)
        key = (frozenset(v.cells for v in held), depth, weak)
        if depth == 0 or key in self._failed:
            return None
        for tool in self.tools:
            for binding in self._bindings(tool, held):
                found = self._call(tool, binding, held, depth, made, weak)
                if found is not None:
                    return found
                break
        for v, inside, tool, slot in self._tests(held):
            narrowed = Var(v.name, v.cells & inside, intersection(v.schema, slot.schema))
            then = self._replace(held, narrowed)
            yes = None
            for binding in self._bindings(tool, then, forced=(slot.name, narrowed)):
                yes = self._call(tool, binding, then, depth - 1, made, weak)
                break
            if yes is None:
                continue
            rest = Var(v.name, v.cells - inside, intersection(v.schema, complement(slot.schema)))
            no = self._solve(self._replace(held, rest), depth - 1, made, weak)
            if no is None and weak:
                no = (Stop(v.name),)
            if no is not None:
                return (Test(v.name, f"{tool.name}.{slot.name}", yes, no),)
        self._failed.add(key)
        return None

    def _call(
        self,
        tool: Tool,
        binding: tuple[tuple[str, Var], ...],
        held: tuple[Var, ...],
        depth: int,
        made: int,
        weak: bool,  # noqa: FBT001
    ) -> Program | None:
        """Make the call, then solve from the state its results extend.

        A call whose every result type is already held adds nothing a later step could
        use, so it is not made.
        """
        if depth <= 0:
            return None
        label = f"c{made + 1}"
        fresh = tuple(
            Var(f"{label}.{r.name}", self.abstraction.cells_of(r.schema), r.schema)
            for r in tool.results
        )
        known = {v.cells for v in held}
        if all(f.cells in known for f in fresh):
            return None
        rest = self._solve(held + fresh, depth - 1, made + 1, weak)
        if rest is None:
            return None
        return (Call(label, tool.name, tuple((a, v.name) for a, v in binding)), *rest)

    def _bindings(
        self,
        tool: Tool,
        held: tuple[Var, ...],
        forced: tuple[str, Var] | None = None,
    ) -> Iterable[tuple[tuple[str, Var], ...]]:
        """Yield bindings of the required arguments whose whole object is proven valid.

        ``forced`` pins one argument to one variable: the narrowed value a test admitted.
        """
        required = [s for s in tool.args if s.required]
        options = []
        for slot in required:
            inside = self.abstraction.cells_of(slot.schema)
            if forced is not None and slot.name == forced[0]:
                fits = [forced[1]] if forced[1].cells <= inside else []
            else:
                fits = [v for v in held if v.cells <= inside]
            if not fits:
                return
            options.append(fits)
        for choice in itertools.islice(itertools.product(*options), MAX_BINDINGS):
            binding = tuple(zip((s.name for s in required), choice, strict=True))
            if self._whole_input(tool, binding):
                yield binding

    def _whole_input(self, tool: Tool, binding: tuple[tuple[str, Var], ...]) -> bool:
        """Return whether the argument record is proven inside the whole input schema.

        For a plain input schema it is, by the per-argument checks already made: each bound
        variable's cells lie in its slot's, and `_bindings` binds every required argument.
        Otherwise valgebra decides.
        """
        if tool.plain:
            return True
        key = (tool.name, tuple(v.schema for _, v in binding))
        if key not in self._whole:
            record = Validator({a: v.schema for a, v in binding})
            self._whole[key] = record.is_subtype_of(tool.input)
        return self._whole[key]

    def _tests(self, held: tuple[Var, ...]) -> Iterable[tuple[Var, Cells, Tool, Slot]]:
        """Yield guarded calls worth branching on: a held variable an argument only overlaps.

        A test asks whether a tool can take the value, and its *then* branch calls that tool
        with it. A test whose only use were to return the narrowed value would let any input
        that happens to look like an answer be returned as one. Variables are tried newest
        first, so a value a tool produced is preferred to a task input of the same type.
        """
        for tool in self.tools:
            for slot in tool.args:
                if not slot.required:
                    continue
                inside = self.abstraction.cells_of(slot.schema)
                for v in reversed(held):
                    overlap = v.cells & inside
                    if overlap and overlap != v.cells:
                        yield v, inside, tool, slot

    @staticmethod
    def _replace(held: tuple[Var, ...], v: Var) -> tuple[Var, ...]:
        return tuple(v if h.name == v.name else h for h in held)


@dataclass(frozen=True, slots=True)
class Gap:
    """A stop of a weak program, and what is known of the values that reach it."""

    path: str
    var: str
    values: tuple[Any, ...]
    complete: bool
    undecided: int

    def describe(self, examples: int = 3) -> str:
        """Render the gap: every uncovered value when they are known, else a few examples."""
        values = self.values if self.complete else self.values[:examples]
        shown = ", ".join(repr(v) for v in values)
        if self.complete:
            return f"{self.var} in {{{shown}}}"
        extra = f" (+{self.undecided} undecided cells)" if self.undecided else ""
        return f"{self.var}, e.g. {shown}{extra}" if shown else f"{self.var}{extra}"


def gaps(planner: Planner, program: Program) -> list[Gap]:
    """Return every stop of ``program`` with the cells its variable is narrowed to there."""
    by_name = {t.name: t for t in planner.tools}
    held = {v.name: v.cells for v in planner.initial()}
    out: list[Gap] = []
    _gaps(planner, by_name, program, held, "", out)
    return out


def _gaps(
    planner: Planner,
    by_name: dict[str, Tool],
    program: Program,
    held: dict[str, Cells],
    path: str,
    out: list[Gap],
) -> None:
    a = planner.abstraction
    held = dict(held)
    for i, step in enumerate(program):
        match step:
            case Call(label, name, _):
                for r in by_name[name].results:
                    held[f"{label}.{r.name}"] = a.cells_of(r.schema)
            case Test(var, against, then, other):
                inside = a.cells_of(slot_named(planner.tools, against).schema)
                _gaps(
                    planner,
                    by_name,
                    then,
                    held | {var: held[var] & inside},
                    f"{path}{i}.then.",
                    out,
                )
                _gaps(
                    planner,
                    by_name,
                    other,
                    held | {var: held[var] - inside},
                    f"{path}{i}.else.",
                    out,
                )
                return
            case Stop(var):
                values, complete = a.members(held[var])
                undecided = sum(a.cells[c].status == "undecided" for c in held[var])
                out.append(Gap(f"{path}{i}", var, tuple(values), complete, undecided))
                return
            case Return():
                return


def witnesses(tools: Sequence[Tool], task: Task, seed: int = 0, tries: int = 40) -> list[Any]:
    """Draw candidate values for every slot of the library and the task.

    The values seed the abstraction: each one proves the cell it falls in inhabited. One
    stream per slot, seeded by the slot's name, so adding a tool leaves the draws for the
    others unchanged.
    """
    import random  # noqa: PLC0415

    out: list[Any] = []
    named = [(f"{t.name}.{s.name}", s) for t in tools for s in t.args + t.results]
    named += [(f"task.{s.name}", s) for s in task.inputs]
    for name, slot in named:
        if is_native(slot.source):
            # A Python annotation has no JSON Schema to draw from; its listed values, the
            # generic values and the members range arithmetic builds are its witnesses.
            out += native_values(slot.source) or []
            continue
        rng = random.Random(f"{seed}:{name}")
        out += Sampler(slot.root, rng).draw(slot.source, tries)
    return out


def _listed(source: object, root: object) -> list[Any] | None:
    return native_values(source) if is_native(source) else finite(source, root)


def slot_named(tools: Sequence[Tool], against: str) -> Slot:
    """Return the argument slot ``"<tool>.<arg>"`` names."""
    name, _, arg = against.partition(".")
    for t in tools:
        if t.name == name:
            return t.arg(arg)
    msg = f"no tool {name!r}"
    raise KeyError(msg)
