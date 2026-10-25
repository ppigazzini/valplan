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
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any
from urllib.parse import unquote

from annotated_types import Ge, Gt, Le, Len, Lt, MaxLen, MinLen, MultipleOf, Predicate
from valgebra import Regex, Validator, anything, complement, intersection, nothing, recursive, union

NOT_BOOL = complement(bool)

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
        spellings: list[object] = [_literal(value)]
        if float(value).is_integer():
            spellings += [_literal(int(value)), _literal(float(value))]
        return union(*spellings)
    if isinstance(value, list):
        return _fixed([_constant(v) for v in value])
    if isinstance(value, dict):
        return Validator({_field(k): _constant(v) for k, v in value.items()})
    msg = f"constant {value!r} is not a JSON value"
    raise Unsupported(msg)


def _literal(value: object) -> object:
    from typing import Literal  # noqa: PLC0415 - a subscript built from a runtime value

    return Literal[value]  # ty: ignore[invalid-type-form]


def _each(schema: object) -> Validator[Any]:
    return Validator(list[schema])  # ty: ignore[invalid-type-form]


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
        return union(complement(kind), refined)

    def compile(self, schema: object) -> Validator[Any]:
        """Return the set of JSON values ``schema`` admits."""
        if schema is True:
            return JSON
        if schema is False:
            return nothing
        if not isinstance(schema, dict):
            msg = f"a schema is an object or a boolean, got {type(schema).__name__}"
            raise Unsupported(msg)
        if schema is self.root and schema.get("$schema", DRAFT) != DRAFT:
            msg = f"$schema {schema['$schema']!r}: only draft 2020-12 is supported"
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
                msg = f"keyword {keyword!r} is not supported"
                raise Unsupported(msg)
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
    decimal numbers written, so a fractional step is checked in `decimal` arithmetic.
    """
    step = s["multipleOf"]
    if float(step).is_integer():
        return c.guard("number", _number(MultipleOf(int(step))))
    c.opaque.add("multipleOf")
    exact = Decimal(repr(step))

    def multiple(value: float) -> bool:
        return math.isfinite(value) and Decimal(repr(value)) % exact == 0

    return c.guard("number", _number(Predicate(multiple)))


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
    shapes += [_fixed(prefix[:n]) for n in range(1, len(prefix))]
    shapes.append(Validator([*prefix, rest, ...]))
    return c.guard("array", union(*shapes))


def _fixed(parts: list[Validator[Any]]) -> Validator[Any]:
    if not parts:
        return Validator([])
    if len(parts) == 1:
        return intersection(Annotated[list[Any], Len(1, 1)], _each(parts[0]))
    return Validator(parts)


def _contains(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return arrays with an element in the subschema: not every element outside it.

    ``minContains`` and ``maxContains`` without ``contains`` assert nothing.
    """
    if "contains" not in s:
        return JSON
    inner = c.compile(s["contains"])
    if "minContains" not in s and "maxContains" not in s:
        return c.guard("array", intersection(ARRAY, complement(_each(complement(inner)))))
    c.opaque.add("minContains/maxContains")
    low, high = s.get("minContains", 1), s.get("maxContains", math.inf)

    def counted(items: list[Any]) -> bool:
        return low <= sum(inner.is_valid(x) for x in items) <= high

    return c.guard("array", Annotated[list[Any], Predicate(counted)])


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

    return c.guard("object", Annotated[dict[str, Any], Predicate(admits)])


def _property_names(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    c.opaque.add("propertyNames")
    names = c.compile(s["propertyNames"])

    def admits(obj: dict[str, Any]) -> bool:
        return all(names.is_valid(k) for k in obj)

    return c.guard("object", Annotated[dict[str, Any], Predicate(admits)])


def json_key(value: Any) -> object:
    """Return a hashable key under which two JSON values are equal iff JSON Schema says so.

    Numbers compare by exact value (``1`` equals ``1.0``) and never equal a boolean; arrays
    compare in order and objects as sets of key-value pairs.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return (type(value).__name__, value)
    if isinstance(value, (int, float)):
        return ("number", Fraction(value) if math.isfinite(value) else value)
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

    return c.guard("array", Annotated[list[Any], Predicate(unique)])


def _min_properties(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("object", Annotated[dict[str, Any], MinLen(s["minProperties"])])


def _max_properties(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return c.guard("object", Annotated[dict[str, Any], MaxLen(s["maxProperties"])])


def _has(key: str) -> Validator[Any]:
    return Validator({_field(key): anything}).open()


def _dependent_required(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    rules = [
        union(complement(_has(key)), intersection(*(_has(d) for d in deps)))
        for key, deps in s["dependentRequired"].items()
        if deps
    ]
    return c.guard("object", intersection(OBJECT, *rules))


def _dependent_schemas(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    rules = [union(complement(_has(k)), c.compile(sub)) for k, sub in s["dependentSchemas"].items()]
    return c.guard("object", intersection(OBJECT, *rules))


def _all_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return intersection(*(c.compile(sub) for sub in s["allOf"]))


def _any_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return union(*(c.compile(sub) for sub in s["anyOf"]))


def _one_of(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return the values in exactly one branch: each branch minus all the others."""
    subs = [c.compile(sub) for sub in s["oneOf"]]
    return union(
        *(
            intersection(sub, *(complement(other) for j, other in enumerate(subs) if j != i))
            for i, sub in enumerate(subs)
        )
    )


def _not(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    return intersection(JSON, complement(c.compile(s["not"])))


def _if(c: Compiler, s: dict[str, Any]) -> Validator[Any]:
    """Return ``(if & then) | (~if & else)``; ``then`` and ``else`` alone assert nothing."""
    if "if" not in s:
        return JSON
    cond = c.compile(s["if"])
    then = c.compile(s.get("then", True))
    other = c.compile(s.get("else", True))
    return union(intersection(cond, then), intersection(complement(cond), other))


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
    spelled: list[Any] = []
    for value in listed:
        spelled.append(value)
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if number and math.isfinite(value) and float(value).is_integer():
            spelled += [int(value), float(value)]
    compiled = Compiler(root if root is not None else schema).compile(schema)
    out: list[Any] = []
    for value in spelled:
        if compiled.is_valid(value) and not any(_same(value, v) for v in out):
            out.append(value)
    return out


def _same(a: object, b: object) -> bool:
    return type(a) is type(b) and json_key(a) == json_key(b)


def compile_schema(schema: object) -> Validator[Any]:
    """Compile a root schema document."""
    return Compiler(schema).compile(schema)
