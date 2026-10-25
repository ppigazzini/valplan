import json
from pathlib import Path

import pytest

from valplan.program import Call, Return, ShapeError, from_json
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
