# valplan

Plans for tool-using agents in which every call is proven well-typed. MCP tool contracts
(JSON Schema) are compiled into sets that [valgebra](https://github.com/ppigazzini/valgebra)
decides inclusion and emptiness over; the Boolean algebra those sets generate is cut into
finitely many cells; and a planner searches the cells for a program of tool calls and
static type tests on values that reaches the goal whatever values inside their output
schemas the tools return.

Every link of a program is an inclusion between two sets. The planner takes one only on a
proof; the verifier checks each link of a program again, by valgebra alone, and reports it
proven, refuted or undecided. A program proposed elsewhere -- by hand or by a language
model -- is checked link by link the same way. A task no program covers gets a weak program
whose stops name the values left uncovered.

## What it does

| step | how | where |
|---|---|---|
| Compile | JSON Schema draft 2020-12, and drafts 07, 06 and 04 through an upgrade, to valgebra sets over the JSON values `json.loads` returns, keyword by keyword; every valgebra name and recipe in one boundary module | [`valgebra_jsonschema`](https://github.com/ppigazzini/valgebra-jsonschema), `valplan/_valgebra.py` |
| Abstract | the cells of the Boolean algebra of every argument, result, input and goal schema; empty cells proven empty by valgebra, by enumeration of listed values or by interval arithmetic, inhabited cells proven by a member value | `valplan/abstraction.py`, `valplan/ranges.py` |
| Plan | strong planning over the cells: calls whose every argument is a proven subtype, and guarded calls that branch on a static type test of a value; a weak program with named gaps where no strong one exists | `valplan/synth.py` |
| Verify | every inclusion a program depends on, asked of valgebra alone by valgebra-planning's verifier, without the cells or the search; a refuted link comes with a value outside it where one of the examples given is one | `valplan/verify.py` |
| Run | the program on concrete values, each argument and result checked against its contract | `valplan/run.py` |

## Results

```bash
uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
uv run python tools/bench.py --check docs/studies/bench.json
uv run python tools/census.py --check docs/studies/census.json
```

- **The compiler** is [`valgebra-jsonschema`](https://github.com/ppigazzini/valgebra-jsonschema), which publishes its counts against the
  official test suite, real-world schemas and a suite of labeled inclusions.
- **Helpdesk case study** (10 MCP tools, 4 tasks): 35 to 37 cells per task, none of them
  undecided. Two tasks get strong programs, one branching three ways on an invoice's
  status; the verifier proves every check of both (4 of 4, 10 of 10). The other two get
  weak programs that test before they call and whose stop names what is uncovered:
  `c1.tier in {'pro', 'free'}` for escalation, example countries for VAT.
- **Synthetic libraries of 8 to 256 tools**, two families of 3 seeds each, a planted chain
  ending in a branch: a program is found in all 36, and none has an undecided cell. With
  string identifiers and an enum status the verifier proves every check; at 256 tools, 95
  predicates make 97 cells. With integer quotas and measures the program branches on a
  measure range, 597 predicates make up to 984 cells, and the verifier proves every check;
  80 runs against
  tools returning random values inside their output schemas break no contract.
- **The seven MCP reference servers** (66 tools, their listings stored): read through
  [`valgebra-planning`](https://github.com/ppigazzini/valgebra-planning)'s contract reader, 31
  carry an `outputSchema`; cut as its planner cuts them, they give 127 cells, 92 undecided, 91
  of those arrays of records met with complements valgebra does not part.
- **A hand-written chain with the typical mistake** (escalating every customer) is refuted
  at the one binding that is wrong, `c1.tier <= escalate.tier`, with the value `'free'`,
  and at the argument record that carries it.

```
c1 = find_customer(email=email)
c2 = latest_invoice(customer_id=c1.customer_id)
if c2.status in refund_invoice.invoice_status:
    c3 = refund_invoice(invoice_id=c2.invoice_id, amount_cents=c2.amount_cents, invoice_status=c2.status)
    return c3.refund_id
else:
    if c2.status in void_invoice.invoice_status:
        c3 = void_invoice(invoice_id=c2.invoice_id, invoice_status=c2.status)
        return c3.credit_note_id
    else:
        return c2.status
```

## Running

```bash
uv sync
uv run python tools/case.py examples/helpdesk      # plan, verify and print every task
uv run pytest
uv run ruff check && uv run ruff format --check && uv run ty check
uv run python tools/check_markdown.py
```

See [`docs/`](docs/README.md) for the method, the compiler's semantics, the results and
their limits.

## Citing

[doi:10.5281/zenodo.23686600](https://doi.org/10.5281/zenodo.23686600) cites every
version; version 0.0.1 is
[doi:10.5281/zenodo.23686601](https://doi.org/10.5281/zenodo.23686601).
[`CITATION.cff`](CITATION.cff) holds the record.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
