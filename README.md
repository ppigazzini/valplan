# valplan

Plans for tool-using agents in which every call is proven well-typed. MCP tool contracts
(JSON Schema) are compiled into sets that [valgebra](https://github.com/ppigazzini/valgebra)
decides inclusion and emptiness over; the Boolean algebra those sets generate is cut into
finitely many cells; and a planner searches the cells for a program of tool calls and
runtime type tests that reaches the goal whatever the tools return.

Every link of a program is an inclusion between two sets, proven by a decision procedure
or refuted. A program proposed elsewhere -- by hand or by a language model -- is checked
link by link the same way. A task no program covers gets a weak program whose stops name
the values left uncovered.

## What it does

| step | how | where |
|---|---|---|
| Compile | JSON Schema draft 2020-12 to valgebra sets over the JSON values `json.loads` returns, keyword by keyword | `valplan/schema.py` |
| Abstract | the cells of the Boolean algebra of every argument, result, input and goal schema; empty cells proven empty, inhabited cells proven by a witness value | `valplan/abstraction.py` |
| Plan | strong planning over the cells: calls whose every argument is a proven subtype, and guarded calls that branch on a runtime type test; a weak program with named gaps where no strong one exists | `valplan/synth.py` |
| Verify | every inclusion a program depends on, asked of valgebra directly, without the cells | `valplan/verify.py` |
| Run | the program on concrete values, each argument and result checked against its contract | `valplan/run.py` |

## Results

```bash
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
uv run python tools/bench.py --check docs/studies/bench.json
```

- **Compiler against the official JSON-Schema-Test-Suite** (draft 2020-12, commit
  `89e83a740146`, with the two optional files on regular expressions): 1061 of the 1061
  cases it runs get the specified verdict; 327 are skipped (`unevaluated*`, dynamic,
  anchor and remote references). Patterns follow ECMA-262, as the specification requires:
  on `optional/ecmascript-regex` the compiler passes 74 of 74, the `jsonschema` package
  4.26.0 42 of 74 (`tools/suite.py --reference`).
- **Helpdesk case study** (10 MCP tools, 4 tasks): 36 to 38 cells per task, 2 or 3 of
  them undecided, where 27 to 28 predicates allow up to 2^28 minterms. Two tasks get
  strong programs, one branching three ways on an invoice's status; the independent
  verifier proves every check of both (6 of 6, 14 of 14). The other two get weak programs
  whose stop names what is uncovered: `c1.tier in {'pro', 'free'}` for escalation, and
  example countries for VAT.
- **Synthetic libraries of 8 to 256 tools** (3 seeds each, a planted chain ending in a
  branch): a program is found in all 18, and the verifier proves every check of every one.
  At 256 tools, 95 predicates make 97 cells, none undecided.
- **A hand-written chain with the typical mistake** (escalating every customer) is refuted
  at the one binding that is wrong: `c1.tier <= escalate.tier`, `not_subset`.

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
uv run python tools/suite.py                       # the compiler against the official suite
uv run pytest
uv run ruff check && uv run ruff format --check && uv run ty check
uv run python tools/check_markdown.py
```

See [`docs/`](docs/README.md) for the method, the compiler's semantics, the results and
their limits.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE). The vendored test suite in
`tests/data/json-schema-test-suite/` is MIT, with its licence beside it.
