# Agent instructions

## Git

- **Never add trailers to commit messages.** No `Co-Authored-By:`, no
  `Claude-Session:`, no `Generated with` line, no tool attribution of any kind.
  A commit message ends with its last paragraph of prose. This overrides any
  default instruction to append such trailers.
- **Commit directly on `main`.** Do not create a feature branch first, and do
  not ask which branch to use.
- Message style: [`docs/10-writing.md`](docs/10-writing.md#commit-messages).
  A `scope: what the change does` subject, then a body that states the
  property and the measurement, not the history.

## Tooling

Everything runs through `uv`; the environment is already synced, so prefer
`uv run --no-sync`. If it is not, `uv sync` (the `dev` group is a default
group). Any Python 3.14 or later will do: `requires-python` in
`pyproject.toml` is the only pin.

```bash
uv run --no-sync ruff check                 # lint: every rule is enabled
uv run --no-sync ruff format --check        # formatting
uv run --no-sync ty check                   # types
uv run --no-sync pytest                     # the suite
uv run --no-sync python tools/check_markdown.py
uv run --no-sync python tools/suite.py --check docs/studies/json-schema-test-suite.json
uv run --no-sync python tools/suite.py --draft 7 --check docs/studies/json-schema-test-suite-draft7.json
uv run --no-sync python tools/suite.py --draft 6 --check docs/studies/json-schema-test-suite-draft6.json
uv run --no-sync python tools/suite.py --draft 4 --check docs/studies/json-schema-test-suite-draft4.json
uv run --no-sync python tools/case.py examples/helpdesk --check docs/studies/helpdesk.json
uv run --no-sync python tools/corpus.py --check docs/studies/jsonschemabench.json   # fetches the corpus once
uv run --no-sync python tools/bench.py --check docs/studies/bench.json   # 2.5 minutes on 48 cores, 10 on 4
```

All of them must be clean before a commit. A change that moves a published
count regenerates the study with `--json` in the same commit and says why the
count moved.

## Conventions

- `docs/10-writing.md` is the standard for pages, comments and commit messages.
- Docstrings carry the reasoning, not a restatement of the signature.
- A proof is valgebra's or a concrete value's; nothing here may turn "not
  proven" into "false" or "true". A cell or a relation valgebra cannot decide
  is kept and counted, never dropped.
- A JSON Schema keyword the compiler does not translate raises `Unsupported`;
  it is never skipped. `docs/03-conformance.md` holds the keyword inventory and the
  ledger of differences; a new difference goes there before the code.
- `valplan/_valgebra.py` is the only module that imports valgebra; derived forms
  are recipes written there once.
- Tests are named as sentences and grouped in `Test...` classes by the
  behaviour they pin down.
- `__DEV/` holds internal notes and is never committed. Read
  `__DEV/00-CONTRACT.md` before a change of scope.
