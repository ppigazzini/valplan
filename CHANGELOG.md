# Changelog

What changes between the versions Zenodo archives, for a reader holding a version's DOI.
[doi:10.5281/zenodo.23686600](https://doi.org/10.5281/zenodo.23686600) resolves to the newest.

## 0.0.2 - 2026-11-17

### Changed

- JSON Schema is read by [valgebra-jsonschema](https://github.com/ppigazzini/valgebra-jsonschema)
  0.0.5, and each tool's slots by [valgebra-planning](https://github.com/ppigazzini/valgebra-planning)
  0.0.5's contract reader, on valgebra 0.0.32; each is held below its next `0.0.x` minor.
- Every program is judged by valgebra-planning's verifier. A tool whose input constrains each
  argument alone gets no link for its argument record, so the helpdesk's strong programs prove
  4 of 4 and 10 of 10 links; no program and no verdict moves.
- `NaN` is a value of no schema, as valgebra-jsonschema reads JSON, so the range rule's special
  numbers are the two infinities.

### Removed

- The compiler, `valplan/schema.py`, and its studies of the JSON-Schema-Test-Suite,
  JSONSchemaBench and the containment suite, which valgebra-jsonschema holds.
- The Python door, `valplan/native.py`: a tool is read from its JSON Schema alone.

### Added

- The census of the seven MCP reference servers' contracts, read offline from stored listings
  and live each week.
- The study of this planner and valgebra-planning's on the same tasks, and the study of each
  cell rule against valgebra-planning's cut.

## 0.0.1 - 2026-10-27

The first version, [doi:10.5281/zenodo.23686601](https://doi.org/10.5281/zenodo.23686601).
