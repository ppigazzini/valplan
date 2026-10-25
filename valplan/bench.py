"""Synthetic tool libraries with a planted solution, for measuring how planning scales.

A library of ``n`` tools over entities ``e0 .. e(k-1)``, each with an identifier type of its
own (a string pattern no other entity's matches) and a status (an enum of three values).

- **The planted chain.** ``e0 -> e1 -> e2 -> e3``: each step reads one identifier and
  returns the next identifier and its status.
- **The planted branch.** Two finishing tools read ``e3``'s identifier and its status:
  ``finish_a`` takes status ``"a"`` and returns a ``ga`` identifier, ``finish_b`` takes
  ``"b"`` or ``"c"`` and returns a ``gb`` identifier. The goal is ``ga`` or ``gb``, so the
  only strong programs test the status, and the shallowest has 4 calls and 1 test on its
  longest path.
- **Distractors.** The rest of the tools read a random entity's identifier, sometimes
  requiring a narrower status, and return another entity's identifier and status; none of
  them returns ``ga`` or ``gb``.

Every draw comes from one seeded `random.Random`, so a library is a function of ``n`` and
the seed.
"""

import random
from typing import Any

STATUS = ["a", "b", "c"]


def _id(entity: str) -> dict[str, Any]:
    return {"type": "string", "pattern": f"^{entity}_[a-z0-9]{{6}}$"}


def _tool(name: str, args: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "inputSchema": {
            "type": "object",
            "properties": args,
            "required": list(args),
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object", "properties": results, "required": list(results)},
    }


def library(n: int, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an MCP ``tools/list`` result of ``n`` tools and the task it plants."""
    rng = random.Random(f"bench:{n}:{seed}")
    entities = [f"e{k}" for k in range(max(6, n // 3))]
    tools = [
        _tool(
            f"step{i}",
            {"id": _id(entities[i])},
            {"id": _id(entities[i + 1]), "status": {"enum": STATUS}},
        )
        for i in range(3)
    ]
    tools.append(
        _tool(
            "finish_a",
            {"id": _id(entities[3]), "status": {"const": "a"}},
            {"id": _id("ga")},
        )
    )
    tools.append(
        _tool(
            "finish_b",
            {"id": _id(entities[3]), "status": {"enum": ["b", "c"]}},
            {"id": _id("gb")},
        )
    )
    for i in range(max(0, n - len(tools))):
        source, target = rng.sample(entities, 2)
        args: dict[str, Any] = {"id": _id(source)}
        if rng.random() < 0.5:  # noqa: PLR2004
            args["status"] = {"enum": rng.sample(STATUS, rng.randint(1, 2))}
        tools.append(_tool(f"distract{i}", args, {"id": _id(target), "status": {"enum": STATUS}}))
    rng.shuffle(tools)
    task = {
        "name": f"bench-{n}-{seed}",
        "inputs": {"type": "object", "properties": {"id": _id(entities[0])}, "required": ["id"]},
        "goal": {"anyOf": [_id("ga"), _id("gb")]},
    }
    return {"tools": tools}, task
