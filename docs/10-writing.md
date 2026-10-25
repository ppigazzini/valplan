# Technical writing

Three surfaces, one standard: state what is true, with the evidence, in as few words as
carry it.

## The standard

**Authoritative.** Write the fact, not the journey to it. "The ladder starts at 640" — not
"we tried starting at 160 and then realised".

**No history.** Not in pages, not in comments, not in commit messages. A text describes
what is, not what was or how it came to be known. Where a past defect is load-bearing,
state the property that prevents it: "a cell inside an `enum` is decided by checking each
listed value, so the spurious remainder valgebra cannot prove empty never reaches the
planner" — never "we saw a spurious cell and then discovered".

**No meta.** Do not describe the text, the process, or who did what. No "this section
covers", no "as mentioned above", no agent, tool or author names, no counts of how long
something went unnoticed.

**No marketing.** No "powerful", "robust", "seamless", "comprehensive", "state of the art".
A property either has a number or is not claimed.

**Lean.** Every sentence carries a fact, a number, or a consequence. Cut anything that
would survive being deleted.

## Claims

A claim needs evidence in the same sentence or the next one.

- **Measured** — give the number and the command. 975 of 975 suite cases pass, from
  `tools/suite.py --check docs/studies/json-schema-test-suite.json`.
- **Inferred** — say so first, not in a trailing caveat. "The mechanism is X" and "X is
  consistent with the data" are different claims.
- **Untested** — say the gap and what would close it. A gap described as a gap is
  information; a gap left implicit is a defect.

Never write a comparative result from one seed without the words "seed N, one sample" in
the same sentence as the number.

## Numbers

Every published number needs a committed command. Prose is not a study: if a number cannot
be grepped out of a command's output, it is not a result.

Quote a rate with its denominator: 975 of 975 cases run, 327 skipped, not "100 %".

A study records counts; a ratio is computed where it is printed, to one decimal place of a
percentage. The counts are the record, and they compare exactly.

## Pages

Structure by what the reader is doing, not by how the code is organised.

State the limit of what a page covers. A page that silently omits a case reads as though
the case does not exist.

Link with relative paths; `tools/check_markdown.py` fails the build on a dead one.

### Markdown that GitHub renders

The renderer is strict and the failures are silent. The checker catches these; the rules
are here so they are not rediscovered.

- Never split a token across the math boundary: write the whole symbol in one span, or
  plain text.
- No bare sub- or superscript spans.
- No spacing macros in inline `$...$`. They render literally.
- Keep a numeric range in one span. `$\sim10^4\text{ to }10^5$`, or plain text.
- Do not glue an opening `$` to a preceding `~` or `-`.
- When wrapping prose, never start a continuation line with `+ `, `- ` or `* `.
- No images, anywhere. A committed plot stops tracking the code that produced it and cannot
  be grepped against a study row.

## Code comments

**The default is no comment.** Code states what it does; a comment is for what the code
cannot state. Most lines need none.

Comment when the reason is not recoverable from the line:

- a value that looks arbitrary and is not
- an ordering that matters
- a library default being overridden
- an invariant a later edit would silently break
- a cheaper-looking alternative that is wrong

**Imperative mood.** "Keep the cell", not "This keeps the cell" or "Keeps the cell". Same
for docstring summaries, which `ruff` enforces.

Name the owner, the invariant and the failure:

```python
# Keep the cell. valgebra could prove it neither empty nor inhabited, so the planner must
# cover it; dropping it would accept programs that fail on a value it may hold.
```

That names what is set, who defaults it otherwise, what happens without it, and the size of
the effect. `# keep it to be safe` carries none of it.

Do not restate the signature, narrate the obvious, or leave commented-out code.

Docstrings follow the numpy convention. A module docstring states what the module is
responsible for and what it must not do. A function docstring states the contract, not the
implementation.

## Commit messages

A commit states what the change does and what it measures. Same standard as everything
else: fact, no history, no meta.

```
scope: what the change does

The defect, stated as a property of the code. What the change does about it. The
measurement. What remains open.
```

- **Subject**: lowercase after the scope, no trailing period, under 72 characters. Scope is
  the module touched — `schema`, `abstraction`, `synth`, `verify`, `run`, `contracts`,
  `study`, `docs`, `tools`.
- **Body**: wrapped at 88. Give the numbers.
- One logical change per commit. A subject needing "and" is two commits.
- No provenance: not who found it, not how, not what was tried first, not how long it stood.
- No references to uncommitted files, external trackers, or the tooling that produced the
  change.

A defect is described in the present tense as a property:

```
`_atom` checks that every element is a symbol before it checks for a connective, so
`(when (p ?x) (q ?x))` is refused as "expected an atom" instead of being named as a
conditional effect. The connective check runs first; `tests/test_schema.py` pins the message.
```

Not: "this was introduced by the previous fix", "found while investigating X", "had been
wrong for four milestones".

If a cause is not established, state what is established and what is open. Do not narrate
the search.

## What not to write

| avoid | write |
|---|---|
| "significantly faster" | "2.68x, 917.2 ms to 342.2 ms" |
| "should work correctly" | the test that shows it does |
| "we discovered that" | the fact |
| "this was broken for months" | the property that makes it correct |
| "obviously", "simply", "just" | nothing; delete |
| "comprehensive", "robust" | the coverage, as a number |
| "note that", "it is worth mentioning" | the note |
