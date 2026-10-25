# Using the package

## Install

```bash
uv sync
```

Python 3.14, as `.python-version` names. Runtime dependencies: valgebra, annotated-types,
typing-extensions.

## Describe a library and its tasks

A library directory holds two files, as `examples/helpdesk/` does.

- `tools.json` is an MCP `tools/list` result: `{"tools": [...]}`, each tool with a `name`,
  an `inputSchema` and an optional `outputSchema`, both object schemas. A tool without
  `properties` takes no arguments. A result field is available to later calls only when
  the output schema requires it.
- `tasks.json` is `{"tasks": [...]}`, each task with a `name`, an `inputs` object schema
  (what the agent holds at the start; required properties only) and a `goal` schema (the
  set the answer must fall in).

## Describe tools in Python

The second door, `valplan/native.py`: a tool is a Python function, its annotated
parameters are its arguments (required unless they have a default) and its return
annotation, a `TypedDict`, gives its results. The annotations are valgebra's own schema
language; no JSON Schema is written.

```python
from typing import Annotated, Literal
from typing_extensions import TypedDict
from valgebra import Regex
from valplan.native import python_impl, python_task, python_tool

TicketId = Annotated[str, Regex(r"T-[0-9]{6}")]


class Escalation(TypedDict, closed=True):
    escalation_id: Annotated[str, Regex(r"ESC-[0-9]{4}")]


def escalate(ticket_id: TicketId, tier: Literal["enterprise"]) -> Escalation: ...


tool = python_tool(escalate)  # a Tool, like one read from tools.json
impl = python_impl(escalate)  # the function, as the runner calls a tool
```

Every annotation must admit JSON values only, since a tool call travels as JSON;
valgebra decides that, and refuses an open `TypedDict` (declare it `closed=True`), a tuple
or an unannotated parameter with the reason. Python's equality is kept: `Literal[1]` is
the integer 1, not the float 1.0. Tools from both doors plan together.
`examples/python/helpdesk.py` plans, verifies and runs a task on three Python tools:

```bash
uv run python examples/python/helpdesk.py
```

## Plan and verify

```bash
uv run python tools/case.py examples/helpdesk
```

Prints one row per task — cells, program kind, calls, tests, stops, checks proven — and
every program. In Python:

```python
from valplan.contracts import task, tools
from valplan.program import render
from valplan.synth import Planner, witnesses
from valplan.verify import verify

planner = Planner(library, goal_task, witnesses(library, goal_task))
program = planner.plan(max_depth=6, weak=True)
print(render(program), planner.weak)
checks = verify(library, goal_task, program)
```

`planner.weak` is true when no program covers every path and the one returned stops on
some; `valplan.synth.gaps(planner, program)` describes each stop.

## Verify a program from elsewhere

A program written by hand or proposed by a language model is JSON, read with
`valplan.program.from_json`, which refuses a block that ends in a call or has a step after
a test or a return:

```json
[
  {"call": "find_customer", "as": "c1", "args": {"email": "email"}},
  {"if": "c1.tier", "in": "escalate.tier",
   "then": [{"call": "escalate", "as": "c2", "args": {"tier": "c1.tier", "ticket_id": "t"}},
            {"return": "c2.escalation_id"}],
   "else": [{"stop": "c1.tier"}]}
]
```

`verify` returns every check along every path with valgebra's answer: `subset` (proven),
`not_subset` (refuted: a value of the variable lies outside the argument), `undecided`, or
`uncovered` for a stop.

## Run a program

```python
from valplan.run import run

answer = run(library, goal_task, program, {"email": "ada@example.org"}, impls)
```

`impls` maps each tool name to a callable from the arguments object to the result object.
Every argument object and every result is checked against its contract; a breach raises
`ContractError` at the call that made it.
