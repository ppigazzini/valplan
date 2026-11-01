import json
from pathlib import Path

import pytest

from valplan.contracts import task, tools
from valplan.program import Call, Return, ShapeError, Stop, Test, from_json
from valplan.verify import verify

NAIVE = Path(__file__).parent.parent / "examples" / "helpdesk" / "naive-escalate.json"


def test_the_naive_escalation_chain_is_refuted_at_the_tier_binding(library, tasks):
    program = from_json(json.loads(NAIVE.read_text(encoding="utf-8"))["program"])
    refuted = [c for c in verify(library, tasks["escalate"], program) if c.relation == "not_subset"]
    assert [(c.path, c.claim) for c in refuted] == [("2", "c1.tier <= escalate.tier")]


def test_an_unbound_variable_and_an_unknown_tool_are_refuted(library, tasks):
    task = tasks["ticket"]
    unbound = (
        Call("c1", "open_ticket", (("customer_id", "who"), ("subject", "subject"))),
        Return("c1.ticket_id"),
    )
    unknown = (Call("c1", "teleport", ()), Return("c1.x"))
    for program, claim in [
        (unbound, "who is bound before open_ticket"),
        (unknown, "tool teleport exists"),
    ]:
        assert claim in [c.claim for c in verify(library, task, program) if not c.holds]


@pytest.mark.parametrize(
    "steps",
    [
        [{"call": "find_customer", "as": "c1", "args": {"email": "email"}}],
        [{"return": "email"}, {"return": "email"}],
        [],
    ],
)
def test_a_malformed_program_is_refused_by_the_reader_and_by_the_verifier(library, tasks, steps):
    with pytest.raises(ShapeError):
        from_json(steps)
    program = tuple(
        Return(s["return"]) if "return" in s else Call(s["as"], s["call"], ()) for s in steps
    )
    checks = verify(library, tasks["ticket"], program)
    assert checks[0].claim.startswith("well-formed program")
    assert checks[0].relation == "not_subset"


def test_a_number_bound_to_a_string_is_not_proven_through_a_nullable_type():
    out = {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]}

    def takes(name, arg):
        properties = {"x": arg}
        return {
            "name": name,
            "inputSchema": {"type": "object", "properties": properties, "required": ["x"]},
            "outputSchema": out,
        }

    nullable = {"anyOf": [{"type": "null"}, {"type": "number"}]}
    lib = tools(
        {
            "tools": [
                {
                    "name": "get",
                    "inputSchema": {"type": "object"},
                    "outputSchema": {
                        "type": "object",
                        "properties": {"v": nullable},
                        "required": ["v"],
                    },
                },
                takes("pos", {"type": "number", "minimum": 0}),
                takes("shout", {"type": "string"}),
            ]
        }
    )
    t = task({"name": "t", "inputs": {"type": "object", "properties": {}}, "goal": True})
    program = from_json(
        [
            {"call": "get", "as": "c1", "args": {}},
            {
                "if": "c1.v",
                "in": "pos.x",
                "then": [{"call": "shout", "as": "c2", "args": {"x": "c1.v"}}, {"return": "c2.r"}],
                "else": [{"return": "c1.v"}],
            },
        ]
    )
    checks = {c.claim: c for c in verify(lib, t, program)}
    assert not checks["c1.v <= shout.x"].holds


@pytest.mark.parametrize(
    "steps",
    [
        [{"call": "find_customer", "as": "c1", "args": {"email": ["email"]}}, {"return": "c1"}],
        [{"call": "find_customer", "as": "c1", "args": None}, {"return": "c1"}],
        [{"call": ["find_customer"], "as": "c1", "args": {}}, {"return": "c1"}],
        [{"if": "email", "in": 3, "then": [{"return": "email"}], "else": [{"stop": "email"}]}],
        [{"if": ["email"], "in": "goal", "then": [{"return": "email"}], "else": []}],
        [{"return": "email", "note": "extra"}],
        ["return email"],
        {"return": "email"},
    ],
)
def test_the_reader_refuses_a_step_that_is_no_shape_of_names(steps):
    with pytest.raises(ShapeError):
        from_json(steps)


@pytest.mark.parametrize(
    "program",
    [
        (Call("c1", "find_customer", (("email", ["email"]),)), Return("c1.customer_id")),  # ty: ignore[invalid-argument-type]
        (Test("email", 3, (Return("email"),), (Stop("email"),)),),  # ty: ignore[invalid-argument-type]
        (Return(["email"]),),  # ty: ignore[invalid-argument-type]
    ],
)
def test_the_verifier_reports_an_ill_typed_program_instead_of_raising(library, tasks, program):
    checks = verify(library, tasks["ticket"], program)
    assert checks[0].claim.startswith("well-formed program")
    assert checks[0].relation == "not_subset"


@pytest.mark.parametrize(
    ("program", "claim"),
    [
        ((Return("nope"),), "nope is bound before return"),
        (
            (Call("c1", "find_customer", (("bogus", "email"),)), Return("c1.customer_id")),
            "find_customer takes bogus",
        ),
        ((Test("nope", "find_customer.email", (Return("email"),), (Stop("email"),)),), "nope is"),
        ((Test("email", "nobody.x", (Return("email"),), (Stop("email"),)),), "nobody.x names"),
    ],
)
def test_a_link_the_program_cannot_make_is_refuted_by_name(library, tasks, program, claim):
    checks = verify(library, tasks["ticket"], program)
    failed = [c for c in checks if c.claim.startswith(claim)]
    assert failed
    assert all(c.relation == "not_subset" for c in failed)


def test_a_test_against_the_goal_narrows_the_then_branch_to_it(library, tasks):
    program = (Test("email", "goal", (Return("email"),), (Stop("email"),)),)
    checks = verify(library, tasks["ticket"], program)
    assert [(c.path, c.relation) for c in checks] == [
        ("0.then.0", "subset"),
        ("0.else.0", "uncovered"),
    ]


def test_a_constraint_across_arguments_is_checked_on_the_whole_record():
    inputs = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
        "dependentRequired": {"a": ["b"]},
    }
    lib = tools({"tools": [{"name": "t", "inputSchema": inputs}]})
    goal_task = task({"name": "g", "inputs": inputs, "goal": True})
    checks = {
        c.claim: c.relation
        for c in verify(lib, goal_task, (Call("c1", "t", (("a", "a"),)), Return("a")))
    }
    assert checks["a <= t.a"] == "subset"
    assert checks["arguments <= t input"] == "not_subset"


def test_a_program_built_past_the_nesting_bound_is_reported_ill_formed(library, tasks):
    program: tuple = (Return("email"),)
    for _ in range(300):
        program = (Test("email", "goal", program, (Stop("email"),)),)
    checks = verify(library, tasks["ticket"], program)
    assert checks[0].claim.startswith("well-formed program: tests nest past")
