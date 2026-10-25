"""Every valgebra name the package uses, and the recipes it composes from them.

Nothing else in the package imports valgebra: a valgebra release that renames or moves
a name is one file's edit here, and a test holds the boundary. The names come from the
``valgebra`` package, whose ``__all__`` is the supported surface, never from the
extension module underneath it.

valgebra ships the minimal Boolean algebra and leaves the derived forms to be composed;
the ones this package needs are written once, below, as the recipes of valgebra's own
documentation (`docs/04-algebra.md`, "Composition recipes"). A bound reaches valgebra as
an ``annotated_types`` marker, the one constraint vocabulary it reads.
"""

from typing import Annotated, Any

from annotated_types import Len, Predicate
from valgebra import (
    Regex,
    ValidationError,
    Validator,
    anything,
    complement,
    intersection,
    nothing,
    recursive,
    union,
)

__all__ = [
    "NOT_BOOL",
    "Regex",
    "ValidationError",
    "Validator",
    "anything",
    "complement",
    "each",
    "exactly_one",
    "fixed",
    "guard",
    "has",
    "implies",
    "intersection",
    "nothing",
    "opaque",
    "recursive",
    "union",
]

#: Every value but a `bool`, which subclasses `int` and so lies inside a bare `int`.
NOT_BOOL = complement(bool)


def implies(condition: object, then: object, otherwise: object = anything) -> Validator[Any]:
    """Return ``(condition & then) | (~condition & otherwise)``: the conditional recipe."""
    return union(intersection(condition, then), intersection(complement(condition), otherwise))


def guard(kind: object, refined: object) -> Validator[Any]:
    """Return the values outside ``kind``, or the ``refined`` ones: a keyword's scope.

    It is `implies` with nothing to say outside the kind, written as the union it reduces
    to, which keeps the normal form one level shallower.
    """
    return union(complement(kind), refined)


def has(key: str) -> Validator[Any]:
    """Return the mappings that carry ``key``: an open record requiring it."""
    return Validator({key: anything}).open()


def exactly_one(*branches: Validator[Any]) -> Validator[Any]:
    """Return the values in exactly one branch: each branch minus all the others."""
    return union(
        *(
            intersection(b, *(complement(o) for j, o in enumerate(branches) if j != i))
            for i, b in enumerate(branches)
        )
    )


def each(schema: object) -> Validator[Any]:
    """Return the lists whose every element lies in ``schema``."""
    return Validator(list[schema])  # ty: ignore[invalid-type-form]


def fixed(parts: list[Validator[Any]]) -> Validator[Any]:
    """Return the lists of exactly these elements, position by position.

    A one-element list literal is valgebra's homogeneous list, so a fixed length of one
    is a homogeneous list pinned to length one.
    """
    if not parts:
        return Validator([])
    if len(parts) == 1:
        return intersection(Annotated[list[Any], Len(1, 1)], each(parts[0]))
    return Validator(parts)


def opaque(base: object, test: Any) -> Validator[Any]:
    """Return the members of ``base`` that ``test`` admits: valgebra's callback path.

    Membership is exact; every relation that has to look inside ``test`` answers
    "undecided". It is the last resort, kept as small as the part of a meaning the
    algebra cannot carry.
    """
    return Validator(Annotated[base, Predicate(test)])  # ty: ignore[invalid-type-form]
