r"""Compile JSON Schema (draft 2020-12) into valgebra sets over the JSON value universe.

valgebra ships no JSON Schema import, because its universe is every Python value and JSON
has no bytes, tuples or classes. Here the universe is fixed to what ``json.loads`` returns
-- ``None``, ``bool``, ``int``, ``float``, ``str``, ``list`` and ``dict`` with ``str`` keys,
nested -- and on that universe the translation is exact for the keywords it accepts.

Each assertion keyword constrains one kind of instance and passes every other kind, so
``{"minimum": 3}`` admits ``"a"``. A keyword therefore compiles to a *guarded* set,
``complement(kind) | refined``, and a schema object to the meet of its keywords and the
universe. That is the keyword-wise semantics of Attouche et al. (POPL 2024) read as set
algebra, and it is what lets valgebra decide inclusion, equivalence and emptiness between
two compiled schemas.

Two places where JSON Schema's model is not Python's are handled rather than inherited:

- **Numbers compare by value.** ``1`` and ``1.0`` are one number in JSON Schema and
  ``True`` is not a number, so ``integer`` is an ``int`` that is not a ``bool`` or a
  ``float`` that is a multiple of 1, and ``enum``/``const`` admit both spellings of an
  integral constant.
- **``pattern`` searches, in ECMA-262's dialect.** ECMA-262 ``test`` is unanchored and
  valgebra's ``Regex`` matches the whole string, so ``p`` compiles to
  ``(?s:.*)(?:p)(?s:.*)``, after `ecma` rewrites the classes the two dialects read
  differently: ``\\d``, ``\\w``, ``\\s``, ``.`` and ``\\cX``.

Five keywords have no counterpart in valgebra's set language -- ``patternProperties`` and
``propertyNames`` need map keys narrowed by a pattern, ``uniqueItems`` and
``minContains``/``maxContains`` need counting, and ``multipleOf`` with a fractional step
needs decimal arithmetic. They compile to *opaque* predicates: membership stays exact,
while a relation that has to look inside one answers "undecided", never a wrong proof.
`Compiler.opaque` lists the ones a schema used.

A keyword outside the supported set raises `Unsupported` naming it. A compiler that
skipped an assertion it did not understand would admit values the schema refuses, and
every inclusion decided from it would be wrong.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Annotated, Any
from urllib.parse import unquote

from annotated_types import Ge, Gt, Le, Lt, MaxLen, MinLen, MultipleOf

from valplan._valgebra import (
    NOT_BOOL,
    Regex,
    Validator,
    complement,
    each,
    exactly_one,
    fixed,
    guard,
    has,
    implies,
    intersection,
    nothing,
    opaque,
    recursive,
    union,
)

#: Every value ``json.loads`` can return.
JSON = recursive(lambda j: union(None, bool, int, float, str, [j], {str: j}))

NULL = Validator(None)
BOOLEAN = Validator(bool)
#: JSON Schema's integer: a number with no fractional part, however it is written.
INTEGER = intersection(union(int, Annotated[float, MultipleOf(1)]), NOT_BOOL)
NUMBER = intersection(union(int, float), NOT_BOOL)
STRING = Validator(str)
ARRAY = Validator([JSON])
OBJECT = Validator({str: JSON})

KINDS: Mapping[str, Validator[Any]] = {
    "null": NULL,
    "boolean": BOOLEAN,
    "integer": INTEGER,
    "number": NUMBER,
    "string": STRING,
    "array": ARRAY,
    "object": OBJECT,
}

#: Keywords that carry no assertion in draft 2020-12. ``format`` is among them: the
#: format-annotation vocabulary is the default, and an annotation admits every value.
ANNOTATIONS = frozenset(
    {
        "$schema",
        "$vocabulary",
        "$comment",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "format",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "$defs",
        "definitions",
    }
)

DRAFT = "https://json-schema.org/draft/2020-12/schema"
DRAFT7 = frozenset(
    {
        "http://json-schema.org/draft-07/schema#",
        "http://json-schema.org/draft-07/schema",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema",
    }
)

#: Draft 2020-12 keywords translated to sets: exactly, or as an opaque predicate
#: (`Compiler.opaque` records which), or read as part of a sibling's group.
SUPPORTED = frozenset(
    {
        "$id",
        "$ref",
        "prefixItems",
        "items",
        "contains",
        "additionalProperties",
        "properties",
        "patternProperties",
        "dependentSchemas",
        "propertyNames",
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "type",
        "const",
        "enum",
        "multipleOf",
        "maximum",
        "exclusiveMaximum",
        "minimum",
        "exclusiveMinimum",
        "maxLength",
        "minLength",
        "pattern",
        "maxItems",
        "minItems",
        "uniqueItems",
        "maxContains",
        "minContains",
        "maxProperties",
        "minProperties",
        "required",
        "dependentRequired",
    }
)

#: Draft 2020-12 keywords that assert something this compiler does not translate. Every
#: other keyword it has no handler for is outside the vocabularies, so an annotation.
REFUSED = frozenset(
    {
        "unevaluatedProperties",
        "unevaluatedItems",
        "$dynamicRef",
        "$dynamicAnchor",
        "$anchor",
        "$recursiveRef",
        "$recursiveAnchor",
        "additionalItems",
        "dependencies",
    }
)


class Unsupported(ValueError):  # noqa: N818 - the name is the sentence a caller reads
    """A schema uses a keyword or form this compiler does not translate."""


#: The kind each family of assertion keywords constrains, and the ``type`` names in it.
FAMILIES: Mapping[str, tuple[Validator[Any], frozenset[str]]] = {
    "number": (NUMBER, frozenset({"integer", "number"})),
    "string": (STRING, frozenset({"string"})),
    "array": (ARRAY, frozenset({"array"})),
    "object": (OBJECT, frozenset({"object"})),
}


def _number(bound: object) -> Validator[Any]:
    return intersection(union(Annotated[int, bound], Annotated[float, bound]), NOT_BOOL)


def _constant(value: object) -> Validator[Any]:
    """Return the JSON values equal to ``value`` under JSON Schema's equality.

    Numbers compare by value and never equal a boolean; arrays and objects compare
    element-wise and key-wise, so a constant compiles structurally rather than as one
    `Literal`, which would compare with Python's ``==`` and admit ``True`` for ``1``.
    """
    if value is None or isinstance(value, (bool, str)):
        return Validator(_literal(value))
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return nothing
        return union(*(_literal(v) for v in spellings(value)))
    if isinstance(value, list):
        return fixed([_constant(v) for v in value])
    if isinstance(value, dict):
        return Validator({_field(k): _constant(v) for k, v in value.items()})
    msg = f"constant {value!r} is not a JSON value"
    raise Unsupported(msg)


def spellings(value: float) -> list[float]:
    """Return the Python values that spell one JSON number: ``1`` and ``1.0``.

    An integer has a float spelling only when the float is the same number. Above 2**53 a
    float rounds, so ``9007199254740993`` and ``9007199254740992.0`` are two numbers, and
    past the float range there is no float spelling at all.
    """
    if isinstance(value, float):
        return [value, int(value)] if value.is_integer() else [value]
    try:
        twin = float(value)
    except OverflowError:
        return [value]
    return [value, twin] if twin == value else [value]


def _literal(value: object) -> object:
    from typing import Literal  # noqa: PLC0415 - a subscript built from a runtime value

    return Literal[value]  # ty: ignore[invalid-type-form]


def _field(key: str) -> str:
    # valgebra reads a trailing `?` on a record key as "optional"; a JSON key that ends in
    # one cannot be told apart from that marker.
    if key.endswith("?"):
        msg = f"property name {key!r} ends in '?', which valgebra reads as optional"
        raise Unsupported(msg)
    return key


class Compiler:
    """Compile one root document, resolving ``$ref`` against it.

    A reference is compiled as a `valgebra.recursive` fixpoint over its target, so a
    schema that names itself (a tree, a linked list) compiles to the recursive set it
    denotes rather than looping. A target is compiled once and reused.
    """

    def __init__(self, root: object) -> None:
        self.root = root
        self.opaque: set[str] = set()
        #: Keywords outside draft 2020-12's vocabularies, which it says to treat as
        #: annotations: they assert nothing, and each one met is recorded here.
        self.ignored: set[str] = set()
        self._done: dict[str, Validator[Any]] = {}
        self._open: dict[str, Validator[Any]] = {}
        self._typed: list[frozenset[str] | None] = []

    def guard(self, family: str, refined: object) -> Validator[Any]:
        """Return the values outside the family's kind, or ``refined`` ones.

        Where the schema's own ``type`` already confines the instance to the family, the
        guard's other half is empty after the meet with ``type``, so it is left out: the
        set is the same and every decision over it is cheaper.
        """
        kind, names = FAMILIES[family]
        typed = self._typed[-1] if self._typed else None
        if typed is not None and typed <= names:
            return Validator(refined)
        return guard(kind, refined)

    def compile(self, schema: object) -> Validator[Any]:
        """Return the set of JSON values ``schema`` admits."""
        if schema is True:
            return JSON
        if schema is False:
            return nothing
        if not isinstance(schema, dict):
            msg = f"a schema is an object or a boolean, got {type(schema).__name__}"
            raise Unsupported(msg)
        if schema is self.root and schema.get("$schema", DRAFT) not in {DRAFT, *DRAFT7}:
            msg = f"$schema {schema['$schema']!r}: drafts 2020-12 and 07 are supported"
            raise Unsupported(msg)
        named = schema.get("type")
        typed = frozenset(named if isinstance(named, list) else [named]) if named else None
        # A schema confined by `type`, `enum` or `const` admits only JSON values already;
        # the universe is met only where no keyword pins the kind.
        parts: list[object] = [] if typed or "enum" in schema or "const" in schema else [JSON]
        self._typed.append(typed)
        try:
            self._keywords(schema, parts)
        finally:
            self._typed.pop()
        return intersection(*parts) if parts else JSON

    def _keywords(self, schema: dict[str, Any], parts: list[object]) -> None:
        seen: set[str] = set()
        for keyword in schema:
            if keyword in ANNOTATIONS or (keyword == "$id" and schema is self.root):
                continue
            group = _GROUPS.get(keyword, keyword)
            if group in seen:
                continue
            seen.add(group)
            handler = _HANDLERS.get(group)
            if handler is None:
                if keyword in REFUSED:
                    msg = f"keyword {keyword!r} is not supported"
                    raise Unsupported(msg)
                self.ignored.add(keyword)
                continue
            parts.append(handler(self, schema))

    def ref(self, pointer: str) -> Validator[Any]:
        """Return the set a local JSON pointer names, as a fixpoint over its target."""
        if pointer in self._done:
            return self._done[pointer]
        if pointer in self._open:
            return self._open[pointer]
        target = self._resolve(pointer)

        def body(this: Validator[Any]) -> Validator[Any]:
            self._open[pointer] = this
            try:
                return self.compile(target)
            finally:
                del self._open[pointer]

        try:
            built = recursive(body)
        except Unsupported:
            raise
        except Exception as exc:
            msg = f"$ref {pointer!r} does not compile to a contractive fixpoint: {exc}"
            raise Unsupported(msg) from exc
        self._done[pointer] = built
        return built

    def _resolve(self, pointer: str) -> object:
        if not pointer.startswith("#"):
            msg = f"$ref {pointer!r} is not local to the document"
            raise Unsupported(msg)
        if pointer not in {"#", "#/"} and not pointer.startswith("#/"):
            msg = f"$ref {pointer!r} names an anchor; only JSON pointers are supported"
            raise Unsupported(msg)
        node = self.root
        for raw in unquote(pointer[1:]).split("/")[1:]:
            part = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, dict) and part == "items" and "prefixItems" in node:
                # A draft-07 pointer into an `items` array that `upgrade` renamed.
                node = node["prefixItems"]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                msg = f"$ref {pointer!r} names nothing in the document"
                raise Unsupported(msg)
        return node


def _type(_c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    names = s["type"] if isinstance(s["type"], list) else [s["type"]]
    try:
        return union(*(KINDS[n] for n in names))
    except KeyError as exc:
        msg = f"unknown type {exc.args[0]!r}"
        raise Unsupported(msg) from exc


def _enum(_c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return union(*(_constant(v) for v in s["enum"])) if s["enum"] else nothing


def _const(_c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return _constant(s["const"])


def _bound(marker: Callable[[float], object], key: str) -> Callable[..., Validator[Any]]:
    def build(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
        return c.guard("number", _number(marker(s[key])))

    return build


def _multiple_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return multiples of the step: decided for an integral step, opaque for a fraction.

    ``0.0075 % 0.0001`` is not zero in binary floating point, and JSON Schema means the
    decimal numbers written, so a fractional step is checked on the exact rationals those
    numbers denote. `decimal` would round past its context's 28 digits, so ``1e26`` would
    be refused as a multiple of ``0.01``.
    """
    step = s["multipleOf"]
    if isinstance(step, int) or step.is_integer():
        return c.guard("number", _number(MultipleOf(int(step))))
    c.opaque.add("multipleOf")
    exact = Fraction(str(step))

    def multiple(value: float) -> bool:
        finite_value = isinstance(value, int) or math.isfinite(value)
        return finite_value and Fraction(str(value)) % exact == 0

    return c.guard("number", intersection(opaque(int | float, multiple), NOT_BOOL))


def _min_length(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("string", Annotated[str, MinLen(s["minLength"])])


def _max_length(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("string", Annotated[str, MaxLen(s["maxLength"])])


def _pattern(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("string", _search(s["pattern"]))


def _min_items(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("array", Annotated[list[Any], MinLen(s["minItems"])])


def _max_items(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("array", Annotated[list[Any], MaxLen(s["maxItems"])])


def _items(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Compile ``prefixItems`` and ``items`` together, as draft 2020-12 couples them.

    ``prefixItems`` constrains the first positions and admits shorter arrays; ``items``
    constrains every position after the prefix. A one-element list literal is valgebra's
    homogeneous list, so a fixed length of one is written as a length refinement.
    """
    prefix = [c.compile(p) for p in s.get("prefixItems", [])]
    rest = c.compile(s["items"]) if "items" in s else JSON
    shapes: list[object] = [Validator([])]
    shapes += [fixed(prefix[:n]) for n in range(1, len(prefix))]
    shapes.append(Validator([*prefix, rest, ...]))
    return c.guard("array", union(*shapes))


def _contains(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return arrays with an element in the subschema: not every element outside it.

    ``minContains`` and ``maxContains`` without ``contains`` assert nothing.
    """
    if "contains" not in s:
        return JSON
    inner = c.compile(s["contains"])
    if "minContains" not in s and "maxContains" not in s:
        return c.guard("array", intersection(ARRAY, complement(each(complement(inner)))))
    c.opaque.add("minContains/maxContains")
    low, high = s.get("minContains", 1), s.get("maxContains", math.inf)

    def counted(items: list[Any]) -> bool:
        return low <= sum(inner.is_valid(x) for x in items) <= high

    return c.guard("array", opaque(list[Any], counted))


def _object(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Compile ``properties``, ``required`` and ``additionalProperties`` as one record.

    ``additionalProperties`` governs every key ``properties`` does not name, a required one
    included, so a required key outside ``properties`` takes the additional schema. Absent,
    it admits any JSON value; ``false``, it refuses every undeclared key.
    """
    if "patternProperties" in s:
        return _object_by_pattern(c, s)
    props: dict[str, Any] = s.get("properties", {})
    required = set(s.get("required", []))
    extra = c.compile(s.get("additionalProperties", True))
    record: dict[object, object] = {}
    for key, sub in props.items():
        record[_field(key) if key in required else f"{_field(key)}?"] = c.compile(sub)
    for key in sorted(required - set(props)):
        record[_field(key)] = extra
    if not extra.is_empty():
        record[str] = extra
    return c.guard("object", record)


#: ECMA-262 ``WhiteSpace`` and ``LineTerminator``: what ``\s`` matches there. Unicode's
#: White_Space, which valgebra's engine uses, adds U+0085 and lacks U+FEFF.
_ECMA_SPACE = (
    r"\t\n\x0B\x0C\r \u{A0}\u{1680}\u{2000}-\u{200A}\u{2028}\u{2029}\u{202F}\u{205F}\u{3000}"
    r"\u{FEFF}"
)
_DIGIT = "0-9"
_WORD = "A-Za-z0-9_"
_CLASSES = {"d": _DIGIT, "w": _WORD, "s": _ECMA_SPACE}


def ecma(pattern: str) -> str:
    r"""Rewrite an ECMA-262 pattern into valgebra's regex dialect, with ECMA-262's meaning.

    ``\d``, ``\w`` and ``\s`` and their negations become the ASCII and ECMA-262 classes
    they denote there, ``.`` stops at ECMA-262's four line terminators, and ``\cX`` becomes
    the control character it names. Everything else passes through; a construct valgebra's
    engine refuses is refused when the set is built.
    """
    out: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            nxt = pattern[i + 1]
            if nxt.lower() in _CLASSES:
                body = _CLASSES[nxt.lower()]
                negated = nxt.isupper()
                if in_class:
                    out.append(f"[^{body}]" if negated else body)
                else:
                    out.append(f"[^{body}]" if negated else f"[{body}]")
                i += 2
                continue
            if nxt == "c" and i + 2 < len(pattern) and pattern[i + 2].isalpha():
                out.append(f"\\x{{{ord(pattern[i + 2]) % 32:02X}}}")
                i += 3
                continue
            out.append(pattern[i : i + 2])
            i += 2
            continue
        if not in_class and ch == "[":
            if pattern.startswith("[^]", i):
                out.append("(?s:.)")
                i += 3
                continue
            if pattern.startswith("[]", i):
                out.append("[^\\s\\S]")
                i += 2
                continue
            in_class = True
        elif in_class and ch == "]":
            in_class = False
        elif not in_class and ch == ".":
            out.append(r"[^\n\r\u{2028}\u{2029}]")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _search(pattern: str) -> Validator[Any]:
    try:
        return Validator(Annotated[str, Regex(f"(?s:.*)(?:{ecma(pattern)})(?s:.*)")])
    except Exception as exc:
        msg = f"pattern {pattern!r} is outside valgebra's regex dialect: {exc}"
        raise Unsupported(msg) from exc


def _object_by_pattern(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Compile an object group with ``patternProperties`` to an opaque predicate.

    A key takes the schema of every pattern it matches, and of ``properties`` if named
    there; ``additionalProperties`` governs only a key matched by neither. valgebra's map
    keys are key types or literals, so a key narrowed by a pattern has no clause to sit in.
    """
    c.opaque.add("patternProperties")
    props = {k: c.compile(v) for k, v in s.get("properties", {}).items()}
    patterns = [(_search(p), c.compile(v)) for p, v in s["patternProperties"].items()]
    extra = c.compile(s.get("additionalProperties", True))
    required = list(s.get("required", []))

    def admits(obj: dict[str, Any]) -> bool:
        if any(k not in obj for k in required):
            return False
        for key, value in obj.items():
            matched = [sub for regex, sub in patterns if regex.is_valid(key)]
            if key in props:
                matched.append(props[key])
            if not matched:
                matched = [extra]
            if not all(sub.is_valid(value) for sub in matched):
                return False
        return True

    return c.guard("object", opaque(dict[str, Any], admits))


def _property_names(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    c.opaque.add("propertyNames")
    names = c.compile(s["propertyNames"])

    def admits(obj: dict[str, Any]) -> bool:
        return all(names.is_valid(k) for k in obj)

    return c.guard("object", opaque(dict[str, Any], admits))


def json_key(value: Any) -> object:
    """Return a hashable key under which two JSON values are equal iff JSON Schema says so.

    Numbers compare by exact value (``1`` equals ``1.0``) and never equal a boolean; arrays
    compare in order and objects as sets of key-value pairs.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return (type(value).__name__, value)
    if isinstance(value, (int, float)):
        exact = isinstance(value, int) or math.isfinite(value)
        return ("number", Fraction(value) if exact else value)
    if isinstance(value, list):
        return ("array", tuple(json_key(v) for v in value))
    if isinstance(value, dict):
        return ("object", frozenset((k, json_key(v)) for k, v in value.items()))
    return ("other", id(value))


def _unique_items(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    if not s["uniqueItems"]:
        return JSON
    c.opaque.add("uniqueItems")

    def unique(items: list[Any]) -> bool:
        keys = [json_key(v) for v in items]
        return len(set(keys)) == len(keys)

    return c.guard("array", opaque(list[Any], unique))


def _min_properties(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("object", Annotated[dict[str, Any], MinLen(s["minProperties"])])


def _max_properties(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("object", Annotated[dict[str, Any], MaxLen(s["maxProperties"])])


def _dependent_required(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    rules = [
        implies(has(_field(key)), intersection(*(has(_field(d)) for d in deps)))
        for key, deps in s["dependentRequired"].items()
        if deps
    ]
    return c.guard("object", intersection(OBJECT, *rules))


def _dependent_schemas(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    rules = [implies(has(_field(k)), c.compile(sub)) for k, sub in s["dependentSchemas"].items()]
    return c.guard("object", intersection(OBJECT, *rules))


def _all_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return intersection(*(c.compile(sub) for sub in s["allOf"]))


def _any_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return union(*(c.compile(sub) for sub in s["anyOf"]))


def _one_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return the values in exactly one branch."""
    return exactly_one(*(c.compile(sub) for sub in s["oneOf"]))


def _not(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return intersection(JSON, complement(c.compile(s["not"])))


def _if(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return ``(if & then) | (~if & else)``; ``then`` and ``else`` alone assert nothing."""
    if "if" not in s:
        return JSON
    return implies(
        c.compile(s["if"]), c.compile(s.get("then", True)), c.compile(s.get("else", True))
    )


def _ref(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.ref(s["$ref"])


def _schema_id(_c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    del s
    msg = "keyword '$id' changes the base URI; only local references are supported"
    raise Unsupported(msg)


#: Keywords draft 2020-12 couples: each group compiles once, from all its members.
_GROUPS: Mapping[str, str] = {
    "prefixItems": "items",
    "minContains": "contains",
    "maxContains": "contains",
    "required": "properties",
    "additionalProperties": "properties",
    "patternProperties": "properties",
    "then": "if",
    "else": "if",
}

_HANDLERS: dict[str, Callable[[Compiler, dict[str, Any]], Validator[Any]]] = {
    "type": _type,
    "enum": _enum,
    "const": _const,
    "minimum": _bound(Ge, "minimum"),
    "maximum": _bound(Le, "maximum"),
    "exclusiveMinimum": _bound(Gt, "exclusiveMinimum"),
    "exclusiveMaximum": _bound(Lt, "exclusiveMaximum"),
    "multipleOf": _multiple_of,
    "minLength": _min_length,
    "maxLength": _max_length,
    "pattern": _pattern,
    "items": _items,
    "minItems": _min_items,
    "maxItems": _max_items,
    "contains": _contains,
    "properties": _object,
    "propertyNames": _property_names,
    "uniqueItems": _unique_items,
    "minProperties": _min_properties,
    "maxProperties": _max_properties,
    "dependentRequired": _dependent_required,
    "dependentSchemas": _dependent_schemas,
    "allOf": _all_of,
    "anyOf": _any_of,
    "oneOf": _one_of,
    "not": _not,
    "if": _if,
    "$ref": _ref,
    "$id": _schema_id,
}


def finite(schema: object, root: object = None) -> list[Any] | None:
    """Return every JSON value ``schema`` admits when it lists them, else None.

    A schema with ``enum`` or ``const``, a ``boolean`` or ``null`` type, or an ``allOf``
    holding one of these admits only the values listed there, filtered by the rest of the
    schema. Each integral number is listed in both spellings, ``1`` and ``1.0``, which are
    one JSON number and two Python values. The list is what lets a cell inside such a
    schema be decided by checking each value rather than by asking about the cell's set.

    A listed array or object is not enumerated: each number inside it has its spellings
    too, and a list missing one of the combinations would let a cell holding it be called
    empty. Such a schema returns None and its cells are left to valgebra.
    """
    if not isinstance(schema, dict):
        return [] if schema is False else None
    if "enum" in schema:
        listed = list(schema["enum"])
    elif "const" in schema:
        listed = [schema["const"]]
    elif schema.get("type") == "boolean":
        listed = [True, False]
    elif schema.get("type") == "null":
        listed = [None]
    else:
        subs = [finite(sub, root) for sub in schema.get("allOf", [])]
        known = [s for s in subs if s is not None]
        if not known:
            return None
        listed = known[0]
    if any(isinstance(value, (list, dict)) for value in listed):
        return None
    spelled: list[Any] = []
    for value in listed:
        if isinstance(value, float) and not math.isfinite(value):
            continue
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        spelled += spellings(value) if number else [value]
    compiled = Compiler(root if root is not None else schema).compile(schema)
    out: list[Any] = []
    for value in spelled:
        if compiled.is_valid(value) and not any(_same(value, v) for v in out):
            out.append(value)
    return out


@dataclass(frozen=True, slots=True)
class Interval:
    """A numeric schema that is a range and nothing more: its kind, bounds and step.

    A missing bound is None. A bound is the exact value of the number ``json.loads``
    returned, which is what membership compares against: ``1e23`` is the double
    99999999999999991611392, not 10**23, and ``0.1`` is the double nearest one tenth. A
    reading of the decimal written would prove inclusions membership refutes, at the
    integers between the two. ``step`` is an integral
    ``multipleOf``: the range then holds only the multiples of it, which are integers
    whatever ``type`` says.
    """

    integer: bool
    low: Fraction | None = None
    low_open: bool = False
    high: Fraction | None = None
    high_open: bool = False
    step: int | None = None


_RANGE_KEYS = frozenset(
    {"type", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)


def interval(schema: object) -> Interval | None:
    """Return the range a schema denotes when it is ``type``, bounds and a step alone.

    A fractional ``multipleOf`` is not a step: it is opaque (`_multiple_of`), so a schema
    carrying one is not a range. Nor is one with a non-finite bound, which ``json.loads``
    returns for ``1e400``: no exact rational denotes it.
    """
    # A tuple, not a set: `type` may be a list, which a set lookup would try to hash.
    if not isinstance(schema, dict) or schema.get("type") not in ("integer", "number"):
        return None
    if set(schema) - _RANGE_KEYS - ANNOTATIONS:
        return None
    bounds = [schema.get(k) for k in _RANGE_KEYS - {"type"}]
    if any(
        b is not None and (isinstance(b, bool) or not isinstance(b, (int, float))) for b in bounds
    ):
        return None
    if any(isinstance(b, float) and not math.isfinite(b) for b in bounds):
        return None
    step = schema.get("multipleOf")
    if step is not None and (step <= 0 or not (isinstance(step, int) or step.is_integer())):
        return None
    low = high = None
    low_open = high_open = False
    for key, is_open in (("minimum", False), ("exclusiveMinimum", True)):
        if key in schema:
            value = Fraction(schema[key])
            if low is None or value > low or (value == low and is_open):
                low, low_open = value, is_open
    for key, is_open in (("maximum", False), ("exclusiveMaximum", True)):
        if key in schema:
            value = Fraction(schema[key])
            if high is None or value < high or (value == high and is_open):
                high, high_open = value, is_open
    return Interval(
        schema["type"] == "integer",
        low,
        low_open,
        high,
        high_open,
        None if step is None else int(step),
    )


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and json_key(a) == json_key(b)


_ONE = frozenset({"not", "if", "then", "else", "additionalProperties", "contains", "propertyNames"})
_MANY = frozenset({"allOf", "anyOf", "oneOf"})
_MAP = frozenset({"properties", "patternProperties", "definitions", "$defs"})


def upgrade(schema: object) -> object:
    """Rewrite a draft-07 schema into the draft 2020-12 one with the same meaning.

    The keywords whose meaning changed: an ``items`` array is ``prefixItems``, with
    ``additionalItems`` as ``items``; ``dependencies`` splits into ``dependentRequired``
    and ``dependentSchemas``; and a ``$ref`` overrides its siblings, so they are dropped.
    ``definitions`` keeps its name, so every JSON pointer into the document still resolves.
    Only the keywords that hold subschemas are descended into: a property named ``items``
    is a name, not a keyword.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        out: dict[str, Any] = {"$ref": schema["$ref"]}
        if "definitions" in schema:
            out["definitions"] = {k: upgrade(v) for k, v in schema["definitions"].items()}
        return out
    out = {}
    for key, value in schema.items():
        if key == "$schema":
            out[key] = DRAFT
        elif key in {"items", "additionalItems"}:
            out |= _upgrade_items(schema) if key == "items" or "items" not in schema else {}
        elif key == "dependencies":
            out |= _upgrade_dependencies(value)
        elif key in _ONE:
            out[key] = upgrade(value)
        elif key in _MANY:
            out[key] = [upgrade(v) for v in value]
        elif key in _MAP:
            out[key] = {k: upgrade(v) for k, v in value.items()}
        else:
            out[key] = value
    return out


def _upgrade_items(schema: dict[str, Any]) -> dict[str, Any]:
    """Map draft-07 ``items``/``additionalItems`` to 2020-12 ``prefixItems``/``items``."""
    items = schema.get("items", True)
    if not isinstance(items, list):
        return {"items": upgrade(items)} if "items" in schema else {}
    out: dict[str, Any] = {"prefixItems": [upgrade(v) for v in items]}
    if "additionalItems" in schema:
        out["items"] = upgrade(schema["additionalItems"])
    return out


def _upgrade_dependencies(value: dict[str, Any]) -> dict[str, Any]:
    """Split draft-07 ``dependencies`` into ``dependentRequired`` and ``dependentSchemas``."""
    out: dict[str, dict[str, Any]] = {}
    for name, dep in value.items():
        if isinstance(dep, list):
            out.setdefault("dependentRequired", {})[name] = dep
        else:
            out.setdefault("dependentSchemas", {})[name] = upgrade(dep)
    return out


def compile_schema(schema: object) -> Validator[Any]:
    """Compile a root schema document, upgrading a draft-07 one first."""
    if isinstance(schema, dict) and schema.get("$schema") in DRAFT7:
        schema = upgrade(schema)
    return Compiler(schema).compile(schema)
