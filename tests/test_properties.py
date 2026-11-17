"""Properties checked over many random cases rather than a few chosen ones."""

import itertools

import pytest
from valgebra import intersection

from valplan.bench import library
from valplan.contracts import task as read_task
from valplan.contracts import tools as read_tools
from valplan.synth import witnesses


@pytest.mark.parametrize("n", [8, 32])
def test_every_inclusion_and_emptiness_valgebra_proves_holds_on_every_drawn_value(n):
    lib_json, spec = library(n, 0)
    lib, task = read_tools(lib_json), read_task(spec)
    values = witnesses(lib, task)
    preds = list({s.schema: None for t in lib for s in t.args + t.results})
    for a, b in itertools.combinations(preds, 2):
        if a.is_subtype_of(b):
            assert not [v for v in values if a.is_valid(v) and not b.is_valid(v)]
        if intersection(a, b).is_empty():
            assert not [v for v in values if a.is_valid(v) and b.is_valid(v)]


def test_the_helpdesk_decisions_hold_on_every_drawn_value(library, tasks):
    values = witnesses(library, tasks["ticket"])
    preds = list({s.schema: None for t in library for s in t.args + t.results})
    for a, b in itertools.combinations(preds, 2):
        if a.is_subtype_of(b):
            assert not [v for v in values if a.is_valid(v) and not b.is_valid(v)]
        if intersection(a, b).is_empty():
            assert not [v for v in values if a.is_valid(v) and b.is_valid(v)]
