"""Run a tool program on a concrete input, checking every contract at every step.

The runner takes the tools as Python callables from an arguments object to a result
object. It checks each argument object against the tool's input schema and each result
against its whole output schema before using it, so a tool that breaks its own contract
is named at the call, not three steps later where its value is used.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from valplan.contracts import Task, Tool
from valplan.program import Call, Program, Return, Stop, Test
from valplan.synth import slot_named

type Impl = Callable[[dict[str, Any]], dict[str, Any]]


class ContractError(RuntimeError):
    """A value broke the contract at the step it was checked."""


def run(
    tools: Sequence[Tool],
    task: Task,
    program: Program,
    inputs: Mapping[str, Any],
    impls: Mapping[str, Impl],
) -> Any:
    """Execute ``program`` and return its answer."""
    by_name = {t.name: t for t in tools}
    env = dict(inputs)
    for slot in task.inputs:
        if slot.name not in env:
            msg = f"input {slot.name} is missing"
            raise ContractError(msg)
        if not slot.schema.is_valid(env[slot.name]):
            msg = f"input {slot.name}={env[slot.name]!r} is outside its schema"
            raise ContractError(msg)
    steps = list(program)
    while steps:
        step = steps.pop(0)
        match step:
            case Call(label, name, args):
                result = _call(by_name[name], {a: env[v] for a, v in args}, impls[name])
                env |= {f"{label}.{r.name}": result[r.name] for r in by_name[name].results}
            case Test(var, against, then, other):
                target = task.goal if against == "goal" else slot_named(tools, against).schema
                steps = list(then if target.is_valid(env[var]) else other)
            case Stop(var):
                msg = f"no contract covers {var}={env[var]!r}: the program stops here"
                raise ContractError(msg)
            case Return(var):
                if not task.goal.is_valid(env[var]):
                    msg = f"answer {env[var]!r} is outside the goal"
                    raise ContractError(msg)
                return env[var]
    msg = "the program ended without a return"
    raise ContractError(msg)


def _call(tool: Tool, arguments: dict[str, Any], impl: Impl) -> dict[str, Any]:
    """Call ``impl`` and return its result, each side checked against the contract."""
    if not tool.input.is_valid(arguments):
        msg = f"{tool.name} called with {arguments!r}, outside its input schema"
        raise ContractError(msg)
    result = impl(arguments)
    if not tool.output.is_valid(result):
        msg = f"{tool.name} returned {result!r}, outside its output schema"
        raise ContractError(msg)
    for r in tool.results:
        if r.name not in result or not r.schema.is_valid(result[r.name]):
            msg = f"{tool.name} returned {result!r}, breaking its field {r.name}"
            raise ContractError(msg)
    return result
