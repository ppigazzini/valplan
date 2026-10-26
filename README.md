# valplan

Plans for tool-using agents in which every call is proven well-typed. MCP tool contracts
(JSON Schema) are compiled into sets that [valgebra](https://github.com/ppigazzini/valgebra)
decides inclusion and emptiness over; the Boolean algebra those sets generate is cut into
finitely many cells; and a planner searches the cells for a program of tool calls and
runtime type tests that reaches the goal whatever values inside their output schemas the
tools return.

Every link of a program is an inclusion between two sets, proven by a decision procedure
or refuted. A program proposed elsewhere -- by hand or by a language model -- is checked
link by link the same way. A task no program covers gets a weak program whose stops name
the values left uncovered.

## What it does

| step | how | where |
|---|---|---|
| Compile | JSON Schema draft 2020-12, and drafts 07, 06 and 04 through an upgrade, to valgebra sets over the JSON values `json.loads` returns, keyword by keyword; every valgebra name and recipe in one boundary module | `valplan/schema.py`, `valplan/_valgebra.py` |
| Read Python | the second door: a tool is a Python function, its annotated parameters the arguments and a `TypedDict` return the results, in valgebra's own schema language; every annotation proven to admit JSON values only | `valplan/native.py` |
| Abstract | the cells of the Boolean algebra of every argument, result, input and goal schema; empty cells proven empty by valgebra, by enumeration of listed values or by interval arithmetic, inhabited cells proven by a member value | `valplan/abstraction.py`, `valplan/ranges.py` |
| Plan | strong planning over the cells: calls whose every argument is a proven subtype, and guarded calls that branch on a runtime type test; a weak program with named gaps where no strong one exists | `valplan/synth.py` |
| Verify | every inclusion a program depends on, asked of valgebra alone, without the cells or the search; a refuted link comes with a value outside it | `valplan/verify.py` |
| Run | the program on concrete values, each argument and result checked against its contract | `valplan/run.py` |

## Results

```bash
uv run python tools/suite.py --check docs/studies/json-schema-test-suite.json
uv run python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
uv run python tools/bench.py --check docs/studies/bench.json
```

- **Compiler against the official JSON-Schema-Test-Suite** (commit `89e83a740146`):
  draft 2020-12 with the four optional files on regular expressions and large numbers,
  1071 of the 1071 cases it runs; draft-07, 870 of 870; draft-06, 790 of 790; draft-04, 587
  of 587. Skipped: `unevaluated*`, dynamic,
  anchor and remote references. Patterns follow ECMA-262, as the specification requires:
  on `optional/ecmascript-regex` the compiler passes 74 of 74, the `jsonschema` package
  4.26.0 42 of 74 (`tools/suite.py --reference`). Against that package on 400 random
  schemas and 25 random values each, over the keywords the two read alike: no
  disagreement ([`docs/03-conformance.md`](docs/03-conformance.md)).
- **Real-world schemas** (JSONSchemaBench, 9558 schemas from GitHub, the JSON Schema
  Store, Kubernetes and function-calling data): 9299 compile, none crashes; membership
  differs from the `jsonschema` package's on 8 of 387570 values, each a reading the ledger
  records.
- **Helpdesk case study** (10 MCP tools, 4 tasks): 35 to 37 cells per task, none of them
  undecided. Two tasks get strong programs, one branching three ways on an invoice's
  status; the verifier proves every check of both (6 of 6, 14 of 14). The other two get
  weak programs that test before they call and whose stop names what is uncovered:
  `c1.tier in {'pro', 'free'}` for escalation, example countries for VAT.
- **Synthetic libraries of 8 to 256 tools**, two families of 3 seeds each, a planted chain
  ending in a branch: a program is found in all 36, and none has an undecided cell. With
  string identifiers and an enum status the verifier proves every check; at 256 tools, 95
  predicates make 97 cells. With integer quotas and measures the program branches on a
  measure range, 597 predicates make up to 984 cells, and the verifier proves every check
  but the two on each *else* branch, which only the interval rule proves; 80 runs against
  tools returning random values inside their output schemas break no contract.
- **A hand-written chain with the typical mistake** (escalating every customer) is refuted
  at the one binding that is wrong, `c1.tier <= escalate.tier`, with the value `'free'`.

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
