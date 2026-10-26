"""Three helpdesk tools written as Python functions, planned and run with valplan.

    uv run python examples/python/helpdesk.py

The contracts are the functions' own annotations; the program the planner returns runs
on the functions themselves, every argument and result checked against them.
"""

from typing import Annotated, Literal, TypedDict

from annotated_types import MaxLen, MinLen
from valgebra import Regex

from valplan.native import python_impl, python_task, python_tool
from valplan.program import render
from valplan.run import run
from valplan.synth import Planner, gaps, witnesses
from valplan.verify import verify

Email = Annotated[str, Regex(r"[^@\s]+@[^@\s]+\.[a-z]{2,}")]
CustomerId = Annotated[str, Regex(r"cus_[a-z0-9]{8}")]
TicketId = Annotated[str, Regex(r"T-[0-9]{6}")]
EscalationId = Annotated[str, Regex(r"ESC-[0-9]{4}")]
Subject = Annotated[str, MinLen(1), MaxLen(120)]
Tier = Literal["free", "pro", "enterprise"]


class Customer(TypedDict, closed=True):
    """What `find_customer` returns."""

    customer_id: CustomerId
    tier: Tier


class Ticket(TypedDict, closed=True):
    """What `open_ticket` returns."""

    ticket_id: TicketId


class Escalation(TypedDict, closed=True):
    """What `escalate` returns."""

    escalation_id: EscalationId


def find_customer(email: Email) -> Customer:
    """Look up a customer by e-mail address."""
    tier: Tier = "enterprise" if email.endswith(".corp") else "free"
    return Customer(customer_id="cus_" + format(abs(hash(email)) % 10**8, "08d"), tier=tier)


def open_ticket(customer_id: CustomerId, subject: Subject) -> Ticket:
    """Open a support ticket."""
    return Ticket(ticket_id=f"T-{len(customer_id) * 1000 + len(subject):06d}")


def escalate(ticket_id: TicketId, tier: Literal["enterprise"]) -> Escalation:
    """Escalate a ticket to the enterprise team."""
    del tier  # the contract is the point: only an enterprise customer reaches this call
    return Escalation(escalation_id=f"ESC-{int(ticket_id[2:]) % 10000:04d}")


FUNCTIONS = [find_customer, open_ticket, escalate]
TOOLS = [python_tool(fn) for fn in FUNCTIONS]
TASK = python_task("escalate", {"email": Email, "subject": Subject}, EscalationId)


def main() -> None:
    """Plan, verify and run the escalation task on the Python tools."""
    planner = Planner(TOOLS, TASK, witnesses(TOOLS, TASK))
    program = planner.plan(max_depth=6, weak=True)
    if program is None:
        msg = "no program within depth 6"
        raise SystemExit(msg)
    print(render(program))
    for gap in gaps(planner, program):
        print(f"uncovered: {gap.describe()}")
    proven = [c for c in verify(TOOLS, TASK, program) if c.holds]
    print(f"proven {len(proven)} of {len(verify(TOOLS, TASK, program))} checks")
    impls = {fn.__name__: python_impl(fn) for fn in FUNCTIONS}
    answer = run(TOOLS, TASK, program, {"email": "ada@acme.corp", "subject": "help"}, impls)
    print(f"run on an enterprise customer: {answer}")


if __name__ == "__main__":
    main()
