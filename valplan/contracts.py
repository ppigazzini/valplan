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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from valgebra import Validator

from valplan.schema import JSON, Compiler, Unsupported, compile_schema


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


def tool(spec: Mapping[str, Any]) -> Tool:
    """Read one entry of an MCP ``tools/list`` result."""
    name = spec["name"]
    try:
        compiler = Compiler(spec["inputSchema"])
        whole = compiler.compile(spec["inputSchema"])
        args = slots(spec["inputSchema"], required_only=False)
        out = spec.get("outputSchema")
        results = slots(out, required_only=True) if out is not None else ()
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


def task(spec: Mapping[str, Any]) -> Task:
    """Read a task: ``{"name", "inputs": <object schema>, "goal": <schema>}``."""
    goal = spec.get("goal", True)
    return Task(
        spec["name"],
        slots(spec["inputs"], required_only=True),
        compile_schema(goal) if goal is not True else JSON,
        goal,
    )
