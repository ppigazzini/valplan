"""Tool contracts: an MCP tool's arguments and results as typed slots over valgebra sets.

An MCP server lists each tool with an ``inputSchema`` (the arguments object) and, since
the 2025-06-18 revision of the protocol, an optional ``outputSchema`` (the structured
result). An agent does not pass one tool's result to the next whole; it fills each
argument from a value it already holds. So a contract is read as named slots: one per
argument, one per guaranteed result field.

A result field is guaranteed only when the output schema requires it. An optional field
may be absent, and binding it would be a call the contract does not license.

The per-slot schema is the property's own subschema. A constraint the whole object
carries (``allOf``, ``if``/``then``, ``dependentRequired``) is not lost: the verifier
checks the assembled argument object against the whole compiled input schema as well.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from valplan._valgebra import Validator
from valplan.schema import (
    ANNOTATIONS,
    DRAFT7,
    JSON,
    Compiler,
    Unsupported,
    compile_schema,
    upgrade,
)


@dataclass(frozen=True, slots=True)
class Slot:
    """A named, typed value: a tool argument, a result field, or a task input."""

    name: str
    schema: Validator[Any]
    source: object = field(compare=False, repr=False)
    required: bool = True
    #: The document ``source`` sits in, against which its ``$ref`` resolve.
    root: object = field(compare=False, repr=False, default=None)


@dataclass(frozen=True, slots=True)
class Tool:
    """A tool's argument slots, guaranteed result slots, and its whole input schema."""

    name: str
    args: tuple[Slot, ...]
    results: tuple[Slot, ...]
    input: Validator[Any]
    description: str = ""
    opaque: frozenset[str] = frozenset()
    #: Keywords outside the vocabulary, read as annotations (`Compiler.ignored`).
    ignored: frozenset[str] = frozenset()
    #: The input schema constrains each property on its own and nothing across them, so
    #: an argument record is inside it exactly when each bound argument is inside its own
    #: slot and every required argument is bound.
    plain: bool = False
    #: The whole output schema, which the runner checks every result against; the
    #: universe when the tool declares none.
    output: Validator[Any] = field(default=JSON, compare=False, repr=False)

    def arg(self, name: str) -> Slot:
        """Return the argument slot called ``name``."""
        for slot in self.args:
            if slot.name == name:
                return slot
        msg = f"{self.name} has no argument {name!r}"
        raise KeyError(msg)


def slots(schema: Mapping[str, Any], *, required_only: bool) -> tuple[Slot, ...]:
    """Return the property slots of an object schema, in declaration order.

    A ``$ref`` inside a property resolves against ``schema``, the document it sits in. An
    object schema without ``properties`` -- a tool that takes no arguments -- has no slots.
    """
    if schema.get("type") != "object":
        msg = "a contract schema is an object schema"
        raise Unsupported(msg)
    compiler = Compiler(schema)
    required = set(schema.get("required", []))
    return tuple(
        Slot(name, compiler.compile(sub), sub, name in required, schema)
        for name, sub in schema.get("properties", {}).items()
        if name in required or not required_only
    )


def inhabited(found: tuple[Slot, ...], where: str) -> tuple[Slot, ...]:
    """Return ``found``, refusing a slot valgebra proves admits no value.

    Every claim about a result or an input that admits nothing holds vacuously: a program
    returning it is proven, and no run can reach the return.
    """
    for slot in found:
        if slot.schema.is_empty():
            msg = f"{where} {slot.name!r} admits no value: every claim about it holds vacuously"
            raise Unsupported(msg)
    return found


def _current(schema: Any) -> Any:
    """Return ``schema`` in draft 2020-12, upgrading it when it declares draft-07."""
    if isinstance(schema, dict) and schema.get("$schema") in DRAFT7:
        return upgrade(schema)
    return schema


def tool(spec: Mapping[str, Any]) -> Tool:
    """Read one entry of an MCP ``tools/list`` result.

    A schema that declares draft-07, as schemas generated from TypeScript types often do,
    is upgraded first.
    """
    name = spec["name"]
    spec = {
        **spec,
        "inputSchema": _current(spec["inputSchema"]),
        **({"outputSchema": _current(spec["outputSchema"])} if "outputSchema" in spec else {}),
    }
    try:
        compiler = Compiler(spec["inputSchema"])
        whole = compiler.compile(spec["inputSchema"])
        args = slots(spec["inputSchema"], required_only=False)
        out = spec.get("outputSchema")
        results = inhabited(slots(out, required_only=True), "result") if out is not None else ()
        output = Compiler(out).compile(out) if out is not None else JSON
    except Unsupported as exc:
        msg = f"tool {name!r}: {exc}"
        raise Unsupported(msg) from exc
    return Tool(
        name,
        args,
        results,
        whole,
        spec.get("description", ""),
        frozenset(compiler.opaque),
        frozenset(compiler.ignored),
        plain=plain(spec["inputSchema"]),
        output=output,
    )


_PLAIN_KEYS = frozenset({"type", "properties", "required", "additionalProperties"})


def plain(schema: Mapping[str, Any]) -> bool:
    """Return whether an object schema has no constraint across its properties.

    ``additionalProperties`` may be absent, ``true`` or ``false``: a program binds only
    declared arguments, so the clause for undeclared keys never meets a bound one. A
    required key outside ``properties`` is no argument slot, so no binding supplies it, and
    the schema is not plain: the record check then refuses every binding, as it must.
    """
    extra = schema.get("additionalProperties", True)
    declared = schema.get("properties", {})
    return (
        schema.get("type") == "object"
        and set(schema) - _PLAIN_KEYS - ANNOTATIONS == set()
        and extra in (True, False)
        and set(schema.get("required", [])) <= set(declared)
    )


def tools(listing: Mapping[str, Any]) -> tuple[Tool, ...]:
    """Read an MCP ``tools/list`` result: ``{"tools": [...]}``."""
    return tuple(tool(spec) for spec in listing["tools"])


@dataclass(frozen=True, slots=True)
class Task:
    """What the agent holds at the start, and the set its answer must fall in."""

    name: str
    inputs: tuple[Slot, ...]
    goal: Validator[Any]
    goal_source: object = field(compare=False, repr=False, default=True)


#: The names a program gives call results, ``c1.id``: an input spelled so would be read
#: as the result of the call it names.
RESULT_NAME = re.compile(r"c[0-9]+\.")


def task(spec: Mapping[str, Any]) -> Task:
    """Read a task: ``{"name", "inputs": <object schema>, "goal": <schema>}``."""
    goal = _current(spec.get("goal", True))
    inputs = inhabited(slots(_current(spec["inputs"]), required_only=True), "input")
    for slot in inputs:
        if RESULT_NAME.match(slot.name):
            msg = f"input {slot.name!r} is named like a call's result"
            raise Unsupported(msg)
    return Task(
        spec["name"],
        inputs,
        compile_schema(goal) if goal is not True else JSON,
        goal,
    )
