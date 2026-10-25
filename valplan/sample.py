"""Draw JSON values from a JSON Schema: the witnesses that prove a cell inhabited.

valgebra proves emptiness and refutes inclusion, but names no value. A cell it cannot
prove empty may still hold nothing, so a cell counts as inhabited only when a concrete
value is found in it. This module proposes candidates; membership in the compiled set is
the only judge, so a wrong proposal costs a rejection, never a wrong proof.

The generator covers the keywords it can construct values for directly and falls back to
rejection elsewhere: ``not``, ``if`` and an unsatisfiable mix simply yield nothing.
"""

import random
import string
from typing import Any

from valplan.schema import Compiler

_ALPHABET = string.ascii_letters + string.digits + "_-@."


class Sampler:
    """Draw candidate values for the schemas of one document, from one seeded stream."""

    def __init__(self, root: object, rng: random.Random, *, depth: int = 4) -> None:
        self.root = root
        self.rng = rng
        self.depth = depth
        self.compiler = Compiler(root)

    def draw(self, schema: object, tries: int = 40) -> list[Any]:
        """Return up to ``tries`` distinct candidates that the compiled schema admits."""
        target = self.compiler.compile(schema)
        found: list[Any] = []
        seen: set[str] = set()
        for _ in range(tries):
            value = self._value(schema, self.depth)
            key = repr(value)
            if key not in seen and target.is_valid(value):
                seen.add(key)
                found.append(value)
        return found

    def _value(self, schema: object, depth: int) -> Any:  # noqa: C901, PLR0911, PLR0912
        rng = self.rng
        if schema is True or not isinstance(schema, dict):
            return rng.choice([None, True, 0, 1.5, "a", [], {}])
        if "$ref" in schema and schema["$ref"].startswith("#/"):
            node: Any = self.root
            for part in schema["$ref"][2:].split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
            return self._value(node, depth - 1) if depth > 0 else None
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            return rng.choice(schema["enum"])
        for key in ("anyOf", "oneOf"):
            if key in schema:
                return self._value(rng.choice(schema[key]), depth)
        if "allOf" in schema:
            merged = {k: v for k, v in schema.items() if k != "allOf"}
            for sub in schema["allOf"]:
                if isinstance(sub, dict):
                    merged |= sub
            return self._value(merged, depth)
        kinds = schema.get("type", ["null", "boolean", "integer", "number", "string"])
        kind = rng.choice(kinds) if isinstance(kinds, list) else kinds
        if kind == "null":
            return None
        if kind == "boolean":
            return rng.random() < 0.5  # noqa: PLR2004
        if kind in {"integer", "number"}:
            return self._number(schema, integer=kind == "integer")
        if kind == "string":
            return self._string(schema)
        if kind == "array":
            return self._array(schema, depth)
        if kind == "object":
            return self._object(schema, depth)
        return None

    def _number(self, schema: dict[str, Any], *, integer: bool) -> int | float:
        low = schema.get("minimum", schema.get("exclusiveMinimum", -1000))
        high = schema.get("maximum", schema.get("exclusiveMaximum", 1000))
        if "exclusiveMinimum" in schema:
            low += 1
        if "exclusiveMaximum" in schema:
            high -= 1
        low, high = int(low), max(int(low), int(high))
        value = self.rng.randint(low, high)
        step = schema.get("multipleOf")
        if isinstance(step, int) and step > 0:
            value -= value % step
        return value if integer or self.rng.random() < 0.5 else value + 0.5  # noqa: PLR2004

    def _string(self, schema: dict[str, Any]) -> str:
        low = schema.get("minLength", 0)
        high = max(low, schema.get("maxLength", low + 8))
        n = self.rng.randint(low, high)
        text = "".join(self.rng.choice(_ALPHABET) for _ in range(n))
        if "pattern" in schema:
            text = _from_pattern(schema["pattern"], self.rng) or text
        return text

    def _array(self, schema: dict[str, Any], depth: int) -> list[Any]:
        prefix = schema.get("prefixItems", [])
        low = schema.get("minItems", 0)
        high = max(low, schema.get("maxItems", low + 3))
        n = self.rng.randint(low, high) if depth > 0 else low
        items = schema.get("items", True)
        return [self._value(prefix[i] if i < len(prefix) else items, depth - 1) for i in range(n)]

    def _object(self, schema: dict[str, Any], depth: int) -> dict[str, Any]:
        props: dict[str, Any] = schema.get("properties", {})
        required = set(schema.get("required", []))
        out: dict[str, Any] = {}
        for key, sub in props.items():
            if key in required or (depth > 0 and self.rng.random() < 0.5):  # noqa: PLR2004
                out[key] = self._value(sub, depth - 1)
        return out


def _from_pattern(pattern: str, rng: random.Random) -> str | None:
    r"""Build a string for the simple patterns contracts use, or None.

    Covers an anchored sequence of literals, character classes and ``\\d``/``\\w`` with
    ``+``, ``*``, ``?`` and ``{m}``/``{m,n}`` counts. Anything else is left to the caller's
    fallback, and membership decides either way.
    """
    body = pattern.removeprefix("^").removesuffix("$")
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            pool = _ESCAPES.get(body[i + 1], body[i + 1])
            i += 2
        elif ch == "[":
            end = body.find("]", i)
            if end < 0:
                return None
            pool = _expand_class(body[i + 1 : end])
            i = end + 1
        elif ch in "()|.":
            return None
        else:
            pool = ch
            i += 1
        low, high, i = _count(body, i, rng)
        out.extend(rng.choice(pool) for _ in range(rng.randint(low, high)))
    return "".join(out)


_PRINTABLE = string.ascii_letters + string.digits + "_-.@!~+"
_ESCAPES = {"d": string.digits, "w": string.ascii_letters + string.digits + "_", "s": " \t"}


def _expand_class(spec: str) -> str:
    """Return the characters a bracket class admits, from a printable stock for ``[^...]``."""
    negated = spec.startswith("^")
    body = spec[1:] if negated else spec
    chars: list[str] = []
    j = 0
    while j < len(body):
        if body[j] == "\\" and j + 1 < len(body):
            chars.extend(_ESCAPES.get(body[j + 1], body[j + 1]))
            j += 2
        elif j + 2 < len(body) and body[j + 1] == "-":
            chars.extend(chr(c) for c in range(ord(body[j]), ord(body[j + 2]) + 1))
            j += 3
        else:
            chars.append(body[j])
            j += 1
    if negated:
        return "".join(c for c in _PRINTABLE if c not in chars) or "a"
    return "".join(chars) or "a"


def _count(body: str, i: int, rng: random.Random | None = None) -> tuple[int, int, int]:
    """Return the repeat range at ``body[i]`` and the index after it.

    An open-ended repeat is usually short and sometimes long, so that cells carved out by a
    length bound elsewhere -- an e-mail address longer than a subject may be -- get drawn.
    """
    if i < len(body) and body[i] in "+*?":
        if body[i] != "?" and rng is not None and rng.random() < 0.2:  # noqa: PLR2004
            return (*rng.choice([(130, 130), (210, 210)]), i + 1)
        return {"+": (1, 4), "*": (0, 4), "?": (0, 1)}[body[i]] + (i + 1,)
    if i < len(body) and body[i] == "{":
        end = body.find("}", i)
        parts = body[i + 1 : end].split(",")
        low = int(parts[0])
        high = int(parts[1]) if len(parts) > 1 and parts[1] else low + 3 if len(parts) > 1 else low
        return low, high, end + 1
    return 1, 1, i
