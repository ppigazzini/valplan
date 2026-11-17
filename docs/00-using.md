# Using the package

## Install

```bash
uv sync
```

Python 3.15 or later, as `requires-python` in `pyproject.toml` says. Runtime dependencies:
valgebra, valgebra-jsonschema, valgebra-planning and annotated-types.

## Describe a library and its tasks

A library directory holds two files, as `examples/helpdesk/` does.

- `tools.json` is an MCP `tools/list` result: `{"tools": [...]}`, each tool with a `name`,
  an `inputSchema`, an object schema or a `$ref` to one, and an optional `outputSchema`. A
  tool without `properties` takes no arguments. An object output schema gives later calls
  each field it requires, and each required field of a required object field, to three
  levels, named by its path: `c1.customer.id`. Any other output schema -- MCP's revision
  2026-07-28 lets a result be any JSON value -- gives one result, the whole value: `c1.$`.
- `tasks.json` is `{"tasks": [...]}`, each task with a `name`, an `inputs` object schema
  (what the agent holds at the start; required properties only, none named like a call's
  result, `c1.id`) and a `goal` schema (the
  set the answer must fall in).

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
a test or a return, and a step that is not one of the four shapes below with a string
wherever a name belongs:

```json
[
  {"call": "find_customer", "as": "c1", "args": {"email": "email"}},
  {"call": "open_ticket", "as": "c2",
   "args": {"customer_id": "c1.customer_id", "subject": "subject"}},
  {"if": "c1.tier", "in": "escalate.tier",
   "then": [{"call": "escalate", "as": "c3",
             "args": {"tier": "c1.tier", "ticket_id": "c2.ticket_id"}},
            {"return": "c3.escalation_id"}],
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
