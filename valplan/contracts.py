"""Tool contracts: an MCP tool's arguments and results as typed slots over valgebra sets.

An MCP server lists each tool with an ``inputSchema`` (the arguments object) and, since
the 2025-06-18 revision of the protocol, an optional ``outputSchema`` (the structured
result), which the 2026-07-28 revision lets be any schema and the result any JSON value.
An agent does not pass one tool's result to the next whole; it fills each argument from a
value it already holds. So a contract is read as named slots: one per argument, one per
guaranteed result field -- nested fields too, named by their path, ``customer.id`` -- and
one, ``$``, for a result that is no object.

The slots are the ones valgebra-planning's contract reader gives (`valplan/_planning.py`), so
the planner here and valgebra-planning's verifier read one contract alike.

A result field is guaranteed only when the output schema requires it, and every object
on its path too. An optional field may be absent, and binding it would be a call the
contract does not license.

The per-slot schema is the property's own subschema. A constraint the whole object
carries (``allOf``, ``if``/``then``, ``dependentRequired``) is not lost: the verifier
checks the assembled argument object against the whole compiled input schema as well.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from valgebra_jsonschema import (
    ANNOTATIONS,
    JSON,
    Compiler,
    Unsupported,
    compile_schema,
    older,
    upgrade,
)

from valplan._planning import Contract, read_contract
from valplan._valgebra import Validator


@dataclass(frozen=True, slots=True)
class Slot:
    """A named, typed value: a tool argument, a result field, or a task input."""

    name: str
    schema: Validator[Any]
    source: object = field(compare=False, repr=False)
    required: bool = True
    #: The document ``source`` sits in, against which its ``$ref`` resolve.
    root: object = field(compare=False, repr=False, default=None)
    #: For a result, the keys from the tool's result to this slot's value; ``()`` is the
    #: whole result, and None the one key ``name``.
    path: tuple[str, ...] | None = field(compare=False, repr=False, default=None)


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
    #: The tool as valgebra-planning's contract reader reads it, which its verifier reads.
    contract: Contract | None = field(default=None, compare=False, repr=False)

    def arg(self, name: str) -> Slot:
        """Return the argument slot called ``name``."""
        for slot in self.args:
            if slot.name == name:
                return slot
        msg = f"{self.name} has no argument {name!r}"
        raise KeyError(msg)


def _object(schema: object, root: object) -> Mapping[str, Any] | None:
    """Return the object schema ``schema`` denotes, following bare references, or None.

    A contract root that is a bare ``$ref`` -- zod's named schemas are -- names its object
    schema, and ``"type": ["object"]`` is ``"type": "object"``.
    """
    for _ in range(8):
        if not (isinstance(schema, dict) and "$ref" in schema):
            break
        if set(schema) - ANNOTATIONS - {"$ref", "$id"}:
            return None
        schema = Compiler(root).resolve(schema["$ref"])
    if isinstance(schema, dict) and schema.get("type") in ("object", ["object"]):
        return schema
    return None


def slots(schema: Mapping[str, Any], *, required_only: bool) -> tuple[Slot, ...]:
    """Return the property slots of an object schema, in declaration order.

    A ``$ref`` inside a property resolves against ``schema``, the document it sits in. An
    object schema without ``properties`` -- a tool that takes no arguments -- has no slots.
    """
    found = _object(schema, schema)
    if found is None:
        msg = "a contract schema is an object schema"
        raise Unsupported(msg)
    compiler = Compiler(schema)
    required = set(found.get("required", []))
    return tuple(
        Slot(name, compiler.compile(sub), sub, name in required, schema)
        for name, sub in found.get("properties", {}).items()
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
    """Return ``schema`` in draft 2020-12, upgrading it when it declares an older draft."""
    if (draft := older(schema)) is not None:
        return upgrade(schema, draft)
    return schema


def tool(spec: Mapping[str, Any]) -> Tool:
    """Read one entry of an MCP ``tools/list`` result.

    A schema that declares draft-07, as schemas generated from TypeScript types often do, or
    draft-06 or draft-04, is upgraded first.
    """
    name = spec["name"]
    spec = {
        **spec,
        "inputSchema": _current(spec["inputSchema"]),
        **({"outputSchema": _current(spec["outputSchema"])} if "outputSchema" in spec else {}),
    }
    try:
        # Compiled whole first, so a malformed keyword is refused by name before the slots
        # are read; the compilers also name the keywords read opaquely or as annotations.
        compiler = Compiler(spec["inputSchema"])
        compiler.compile(spec["inputSchema"])
        out = spec.get("outputSchema")
        reader = Compiler(out)
        if out is not None:
            reader.compile(out)
        contract = read_contract(spec)
    except Unsupported as exc:
        msg = f"tool {name!r}: {exc}"
        raise Unsupported(msg) from exc
    args = tuple(
        Slot(s.path[0], s.values, s.schema, s.required, root=s.root) for s in contract.arguments
    )
    # An object result is read by its fields, and a whole result only where it is no object:
    # the record a whole object result is would be one more predicate to cut by, whose meets
    # with the fields' complements cost the search and name no value a field does not.
    whole = out is not None and _object(out, out) is None
    fields = tuple(
        Slot(".".join(s.path) or "$", s.values, s.schema, root=s.root, path=s.path)
        for s in contract.results
        if s.path or whole
    )
    names = [s.name for s in fields]
    if len(set(names)) != len(names):
        # A program names a field by its path, so two paths read alike name neither.
        msg = f"tool {name!r}: two result paths read alike among {names}"
        raise Unsupported(msg)
    return Tool(
        name,
        args,
        inhabited(fields, "result"),
        contract.accepts,
        spec.get("description", ""),
        frozenset(compiler.opaque | reader.opaque),
        frozenset(compiler.ignored | reader.ignored),
        plain=contract.plain,
        output=JSON if contract.returns is None else contract.returns,
        contract=contract,
    )


def tools(listing: Mapping[str, Any]) -> tuple[Tool, ...]:
    """Read an MCP ``tools/list`` result: ``{"tools": [...]}``."""
    library = tuple(tool(spec) for spec in listing["tools"])
    distinct(library)
    return library


def distinct(library: Sequence[Tool]) -> None:
    """Refuse a library a program could not name its tools and arguments in.

    A program calls a tool by name and tests against ``"<tool>.<arg>"``. MCP keeps a name
    unique within one server only, and a library joined from two can hold one twice; and
    a dot may sit in a tool name and in an argument name alike, so tool ``a`` with argument
    ``b.c`` and tool ``a.b`` with argument ``c`` spell one test two ways.
    """
    names = [t.name for t in library]
    if twice := sorted({n for n in names if names.count(n) > 1}):
        msg = f"two tools are named {twice[0]!r}"
        raise Unsupported(msg)
    seen: dict[str, str] = {}
    for t in library:
        for slot in t.args:
            spelled = f"{t.name}.{slot.name}"
            if spelled in seen:
                msg = f"{spelled!r} names an argument of {seen[spelled]!r} and of {t.name!r}"
                raise Unsupported(msg)
            seen[spelled] = t.name


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
    schema = _current(spec["inputs"])
    # Compiled whole first, so a malformed keyword is refused by name before the slots
    # are read from it.
    Compiler(schema).compile(schema)
    inputs = inhabited(slots(schema, required_only=True), "input")
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
