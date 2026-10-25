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


def _range(low: int, high: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": low, "maximum": high}


def library(n: int, seed: int, family: str = "strings") -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an MCP ``tools/list`` result of ``n`` tools and the task it plants.

    ``family="numbers"`` plants the same chain over integer ranges instead of statuses:
    every tool also takes a quota ``k`` (10000 to 20000) and returns a measure ``m`` (0 to
    1000), the planted tools accept the task's quota of 15000, and the two finishing tools
    split ``m`` at 500; every distractor's measure straddles 500, so every strong program
    tests it.
    """
    if family == "numbers":
        return _numbers(n, seed)
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


def _numbers(n: int, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(f"bench-numbers:{n}:{seed}")
    entities = [f"e{k}" for k in range(max(6, n // 3))]

    # Quotas live in 10000..20000 and measures in 0..1000, so no quota can be passed where
    # a measure is asked for: the schemas are the only specification the planner reads.
    def quota() -> dict[str, Any]:
        return _range(rng.randrange(10000, 15000), rng.randrange(15000, 20000))

    tools = [
        _tool(
            f"step{i}",
            {"id": _id(entities[i]), "k": quota()},
            {"id": _id(entities[i + 1]), "m": _range(0, 1000)},
        )
        for i in range(3)
    ]
    tools.append(
        _tool("finish_a", {"id": _id(entities[3]), "m": _range(0, 499)}, {"id": _id("ga")})
    )
    tools.append(
        _tool("finish_b", {"id": _id(entities[3]), "m": _range(500, 1000)}, {"id": _id("gb")})
    )
    for i in range(max(0, n - len(tools))):
        source, target = rng.sample(entities, 2)
        # A distractor's measure straddles 500, so it never fits one finishing tool whole:
        # a route around the planted test through a distractor would hide the branch.
        measure = _range(rng.randrange(0, 450), rng.randrange(551, 1000))
        quota_range = quota()
        tools.append(
            _tool(
                f"distract{i}",
                {"id": _id(source), "k": quota_range},
                {"id": _id(target), "m": measure},
            )
        )
    rng.shuffle(tools)
    task = {
        "name": f"bench-numbers-{n}-{seed}",
        "inputs": {
            "type": "object",
            "properties": {"id": _id(entities[0]), "k": _range(15000, 15000)},
            "required": ["id", "k"],
        },
        "goal": {"anyOf": [_id("ga"), _id("gb")]},
    }
    return {"tools": tools}, task
