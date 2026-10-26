"""The second door: tools and tasks written as Python functions and types.

A tool is a function. Its annotated parameters are its arguments -- required unless they
have a default -- and its return annotation gives its results: the keys a `TypedDict`
requires, or, for any other annotation, the whole value as one result, ``$``. The
annotations are valgebra's own schema language (a class, a `Literal`, an `Annotated` bound
or `Regex`, a union, a `TypedDict`, a list), so no JSON Schema is written and none is
translated.

One rule keeps the planner's universe what it is: every annotation must denote JSON
values only, because a tool call and its result travel as JSON whatever language wrote
the tool. valgebra decides that inclusion, so the check is the algebra's, not a list of
allowed forms: an open `TypedDict` (any extra key, any value) or a `tuple` is refused with
the reason, and `closed=True` (PEP 728) is the fix for the first. A class that is no JSON
type, an `IntEnum` or `StrEnum`, passes that inclusion, since its members are ints or
strings, and admits no value a call receives over JSON; it is refused by name, and a
`Literal` of the values it stands for is the fix.

Python's semantics are kept, not JSON Schema's: `Literal[1]` is the integer 1 and not the
float 1.0, and `int` admits `True`. A contract that wants JSON Schema's reading writes it
(`Literal[1, 1.0]`, `Annotated[int, ...] & complement(bool)`), or is written in JSON Schema.
"""

import inspect
import typing
from collections.abc import Callable, Mapping
from types import NoneType, UnionType
from typing import Any, Literal, get_args, get_origin, get_type_hints, is_typeddict

from valplan._valgebra import Validator
from valplan.contracts import RESULT_NAME, Slot, Task, Tool, inhabited
from valplan.schema import JSON, Unsupported

#: The classes of the values `json.loads` returns: a subclass of one, an `IntEnum` or a
#: `StrEnum`, has members that are JSON values to an inclusion check, and yet no value a
#: call receives over JSON is one of them.
_JSON_CLASSES = (NoneType, bool, int, float, str, list, dict)


def _json_classes_only(annotation: object, where: str) -> None:
    """Refuse ``annotation`` where it names a class, or lists a value, outside JSON's own."""
    origin = get_origin(annotation)
    if origin is typing.Annotated:
        _json_classes_only(get_args(annotation)[0], where)
    elif origin is Literal:
        for value in get_args(annotation):
            if type(value) not in _JSON_CLASSES:
                msg = f"{where}: the literal {value!r} is a {type(value).__name__}, no JSON value"
                raise Unsupported(msg)
    elif origin is not None:
        for arg in get_args(annotation):
            _json_classes_only(arg, where)
    elif is_typeddict(annotation):
        for hint in _hints(annotation).values():
            _json_classes_only(hint, where)
    elif isinstance(annotation, type) and annotation not in _JSON_CLASSES:
        msg = (
            f"{where}: no JSON value is a {annotation.__name__}; spell its values as a "
            "Literal of the JSON values they are"
        )
        raise Unsupported(msg)


def _json_only(annotation: object, where: str) -> Validator[Any]:
    """Compile ``annotation`` and refuse it unless every value it admits is a JSON value."""
    _json_classes_only(annotation, where)
    try:
        compiled = Validator(annotation)
    except Exception as exc:
        msg = f"{where}: {annotation!r} is not a schema valgebra reads: {exc}"
        raise Unsupported(msg) from exc
    if not compiled.is_subtype_of(JSON):
        msg = (
            f"{where}: {annotation!r} admits values that are not JSON values; a tool call "
            "travels as JSON (an open TypedDict admits any value: declare it closed=True)"
        )
        raise Unsupported(msg)
    return compiled


def _hints(target: Any) -> dict[str, Any]:
    return get_type_hints(target, include_extras=True)


def python_tool(fn: Callable[..., Any], *, name: str | None = None) -> Tool:
    """Read a Python function as a tool: parameters as arguments, a `TypedDict` as results.

    A function returning nothing (no annotation, or ``None``) is a tool with no results.
    Every parameter must be annotated and must be passable by keyword.
    """
    tool_name = name or getattr(fn, "__name__", "")
    if not tool_name:
        msg = f"{fn!r} has no name; pass name="
        raise Unsupported(msg)
    hints = _hints(fn)
    args: list[Slot] = []
    record: dict[str, object] = {}
    for param in inspect.signature(fn).parameters.values():
        if param.kind in {param.VAR_POSITIONAL, param.VAR_KEYWORD, param.POSITIONAL_ONLY}:
            msg = f"{tool_name}: parameter {param.name!r} cannot be passed by keyword"
            raise Unsupported(msg)
        if param.name not in hints:
            msg = f"{tool_name}: parameter {param.name!r} has no annotation"
            raise Unsupported(msg)
        if param.name.endswith("?"):
            msg = f"{tool_name}: parameter {param.name!r} ends in '?'"
            raise Unsupported(msg)
        annotation = hints[param.name]
        compiled = _json_only(annotation, f"{tool_name}.{param.name}")
        required = param.default is inspect.Parameter.empty
        args.append(Slot(param.name, compiled, annotation, required))
        record[param.name if required else f"{param.name}?"] = compiled
    returned = hints.get("return")
    results = _results(tool_name, returned)
    doc = inspect.getdoc(fn) or ""
    return Tool(
        tool_name,
        tuple(args),
        results,
        Validator(record),
        doc.splitlines()[0] if doc else "",
        plain=True,
        output=Validator(returned) if results else JSON,
    )


def _results(tool_name: str, annotation: object) -> tuple[Slot, ...]:
    if annotation is None or annotation is NoneType:
        return ()
    if not is_typeddict(annotation):
        # A result that is no object is one slot, the whole result, as an MCP tool's is.
        whole = _json_only(annotation, f"{tool_name} -> $")
        return inhabited((Slot("$", whole, annotation, path=()),), f"{tool_name}: result")
    hints = _hints(annotation)
    required = getattr(annotation, "__required_keys__", frozenset(hints))
    found = tuple(
        Slot(key, _json_only(hints[key], f"{tool_name} -> {key}"), hints[key])
        for key in hints
        if key in required
    )
    return inhabited(found, f"{tool_name}: result")


def python_impl(fn: Callable[..., Any]) -> Callable[[dict[str, Any]], Any]:
    """Return ``fn`` as the runner calls a tool: one arguments object in, a result out."""

    def call(arguments: dict[str, Any]) -> Any:
        result = fn(**arguments)
        return {} if result is None else result

    return call


def python_task(name: str, inputs: Mapping[str, object] | type, goal: object) -> Task:
    """Read a task whose inputs and goal are Python annotations.

    ``inputs`` maps each input's name to its annotation, or is a `TypedDict` whose required
    keys are the inputs.
    """
    if isinstance(inputs, type) and is_typeddict(inputs):
        hints = _hints(inputs)
        required = getattr(inputs, "__required_keys__", frozenset(hints))
        named = {k: v for k, v in hints.items() if k in required}
    else:
        named = dict(typing.cast("Mapping[str, object]", inputs))
    slots = tuple(
        Slot(key, _json_only(annotation, f"{name}.{key}"), annotation)
        for key, annotation in named.items()
    )
    inhabited(slots, f"{name}: input")
    for slot in slots:
        if RESULT_NAME.match(slot.name):
            msg = f"input {slot.name!r} is named like a call's result"
            raise Unsupported(msg)
    return Task(name, slots, _json_only(goal, f"{name} goal"), goal)


def native_values(annotation: object) -> list[Any] | None:
    """Return every value a finite annotation admits, or None if it is not finite.

    A `Literal`, `bool` and `None` list their values; a union of finite annotations lists
    them all; an `Annotated` form lists its base's values that meet its markers. Python's
    equality is the annotation's own, so `Literal[1]` lists the integer 1 alone.
    """
    if annotation is None or annotation is NoneType:
        return [None]
    if annotation is bool:
        return [True, False]
    origin = get_origin(annotation)
    if origin is Literal:
        return list(get_args(annotation))
    if origin is UnionType or origin is typing.Union:
        parts = [native_values(a) for a in get_args(annotation)]
        if any(p is None for p in parts):
            return None
        return [v for p in parts if p is not None for v in p]
    if origin is typing.Annotated:
        base = native_values(get_args(annotation)[0])
        if base is None:
            return None
        compiled = Validator(annotation)
        return [v for v in base if compiled.is_valid(v)]
    return None


def is_native(source: object) -> bool:
    """Return whether a slot's source is a Python annotation rather than a JSON Schema."""
    return not isinstance(source, (dict, bool))
