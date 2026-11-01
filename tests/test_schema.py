import contextlib
import random

import pytest
from valgebra import complement, intersection, nothing

from valplan.contracts import task, tool
from valplan.schema import (
    ANNOTATIONS,
    JSON,
    REFUSED,
    SUPPORTED,
    Compiler,
    Unsupported,
    compile_schema,
    json_key,
    upgrade,
)


class TestSemantics:
    def test_an_assertion_passes_every_other_kind(self):
        assert compile_schema({"minimum": 3}).is_valid("a")
        assert not compile_schema({"minimum": 3}).is_valid(2)

    def test_integer_admits_an_integral_float_and_refuses_a_boolean(self):
        integer = compile_schema({"type": "integer"})
        assert integer.is_valid(1.0)
        assert not integer.is_valid(1.5)
        assert not integer.is_valid(True)

    def test_enum_compares_numbers_by_value_and_never_equals_a_boolean(self):
        one = compile_schema({"enum": [1]})
        assert one.is_valid(1.0)
        assert not one.is_valid(True)

    def test_pattern_searches_rather_than_matching_the_whole_string(self):
        assert compile_schema({"pattern": "b+"}).is_valid("abbbc")
        assert not compile_schema({"pattern": "^b+$"}).is_valid("abbbc")

    def test_a_required_key_outside_properties_takes_the_additional_schema(self):
        s = compile_schema({"required": ["x"], "additionalProperties": {"type": "integer"}})
        assert s.is_valid({"x": 1})
        assert not s.is_valid({"x": "1"})

    def test_a_fractional_step_is_checked_in_exact_rational_arithmetic(self):
        compiler = Compiler({"multipleOf": 0.0001})
        assert compiler.compile({"multipleOf": 0.0001}).is_valid(0.0075)
        assert compiler.opaque == {"multipleOf"}

    def test_a_recursive_reference_compiles_to_its_fixpoint(self):
        tree = {
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"kids": {"type": "array", "items": {"$ref": "#/$defs/node"}}},
                }
            },
            "$ref": "#/$defs/node",
        }
        s = compile_schema(tree)
        assert s.is_valid({"kids": [{"kids": []}, {}]})
        assert not s.is_valid({"kids": [1]})


class TestEmbeddedResources:
    def test_an_embedded_id_with_nothing_resolving_inside_is_an_annotation(self):
        # A base URI matters to the references inside its resource; with none, the resource
        # means what its keywords mean.
        schema = {"properties": {"a": {"$id": "#/properties/a", "type": "string", "minLength": 2}}}
        compiled = compile_schema(schema)
        assert compiled.is_valid({"a": "ab"})
        assert not compiled.is_valid({"a": "a"})

    @pytest.mark.parametrize(
        "resource",
        [
            {"$id": "http://example.com/a", "$ref": "#/$defs/b", "$defs": {"b": {}}},
            {"$id": "http://example.com/a", "items": {"$anchor": "x"}},
            {"$id": "http://example.com/a", "$schema": "http://json-schema.org/draft-07/schema#"},
        ],
    )
    def test_an_embedded_id_over_a_reference_or_another_dialect_is_refused(self, resource):
        with pytest.raises(Unsupported, match="'\\$id' changes the base URI"):
            compile_schema({"properties": {"a": resource}})

    def test_a_pointer_through_an_embedded_id_is_refused(self):
        schema = {
            "$defs": {
                "s": {"$id": "http://example.com/s", "properties": {"n": {"type": "integer"}}}
            },
            "$ref": "#/$defs/s/properties/n",
        }
        with pytest.raises(Unsupported, match="passes through an embedded"):
            compile_schema(schema)


class TestContainmentLabels:
    # Two pairs of the containment test suite carry a label the specification refutes; the
    # results page names them, and each value here is the witness.
    def test_the_schema_labeled_universal_leaves_out_a_number(self):
        def tree(n):
            sub = f"#/anyOf/{n}/$defs/sub-item"
            item = {"type": "array", "items": False, "prefixItems": [{"$ref": sub}] * 2}
            defs = {"item": item, "sub-item": {"type": "object", "required": ["foo"]}}
            return {"$defs": defs, "type": "array", "items": False}

        top = [{"$ref": "#/anyOf/0/$defs/item"}] * 3
        neither = [{"$ref": "#/anyOf/1/$defs/item"}] * 3
        schema = {
            "anyOf": [{**tree(0), "prefixItems": top}, {**tree(1), "not": {"prefixItems": neither}}]
        }
        compiled = compile_schema(schema)
        assert not compiled.is_valid(1)
        assert JSON.relation_to(compiled) == "not_subset"

    def test_the_schema_labeled_empty_holds_an_object_named_like_a_reference(self):
        def branch(n, key):
            defs = {"a_string": {"type": "string"}}
            listed = {"enum": [{"$ref": f"#/allOf/{n}/$defs/a_string"}]}
            return {"$defs": defs, **({"not": listed} if key == "not" else listed)}

        compiled = compile_schema({"allOf": [branch(0, "enum"), branch(1, "not")]})
        assert compiled.is_valid({"$ref": "#/allOf/0/$defs/a_string"})
        assert compiled.relation_to(nothing) == "not_subset"


class TestUniverse:
    def test_a_type_list_keeps_the_guard_of_each_other_kind(self):
        # The guard is left out only where `type` confines the value to the keyword's kind.
        compiled = compile_schema({"type": ["integer", "string"], "minimum": 3})
        assert compiled.is_valid("a")
        assert compiled.is_valid(3)
        assert not compiled.is_valid(2)

    @pytest.mark.parametrize("schema", [{"minimum": 3}, {"maxLength": 2}, {"required": ["a"]}])
    def test_a_schema_without_a_type_lies_inside_the_universe(self, schema):
        # A keyword's guard admits every value outside its kind, a tuple included; the meet
        # with the universe keeps the set inside JSON, so `true` is proven to contain it.
        assert compile_schema(schema).is_subtype_of(JSON)


class TestDecisions:
    def test_disjoint_patterns_are_proven_disjoint(self):
        a = compile_schema({"type": "string", "pattern": "^cus_[a-z0-9]{8}$"})
        b = compile_schema({"type": "string", "pattern": "^sub_[a-z0-9]{8}$"})
        assert intersection(a, b).is_empty()

    def test_a_narrower_enum_is_a_subtype(self):
        narrow = compile_schema({"enum": ["pro", "enterprise"]})
        wide = compile_schema({"enum": ["free", "pro", "enterprise"]})
        assert narrow.relation_to(wide) == "subset"
        assert wide.relation_to(narrow) == "not_subset"

    def test_a_tighter_bound_is_a_subtype(self):
        tight = compile_schema({"type": "integer", "minimum": 5, "maximum": 30})
        loose = compile_schema({"type": "integer", "minimum": 1})
        assert tight.is_subtype_of(loose)

    def test_false_is_empty(self):
        assert compile_schema(False).relation_to(nothing) == "subset"


class TestRefusals:
    @pytest.mark.parametrize(
        "schema",
        [
            {"unevaluatedProperties": False},
            {"$ref": "http://example.com/x.json"},
            {"$ref": "#anchor"},
            {"properties": {"a": {"$id": "x", "$ref": "#/$defs/b"}}, "$defs": {"b": {}}},
            {"properties": {"opt?": {"type": "string"}}},
        ],
    )
    def test_it_refuses_what_it_cannot_translate(self, schema):
        with pytest.raises(Unsupported):
            compile_schema(schema)

    def test_it_refuses_a_draft_it_does_not_read(self):
        with pytest.raises(Unsupported, match="2020-12, 07, 06 and 04"):
            compile_schema({"$schema": "https://json-schema.org/draft/2019-09/schema"})


_DRAFTS = {
    "2020-12": None,
    "7": "http://json-schema.org/draft-07/schema#",
    "6": "http://json-schema.org/draft-06/schema#",
    "4": "http://json-schema.org/draft-04/schema#",
}
_KEYWORDS = sorted(
    SUPPORTED | REFUSED | ANNOTATIONS | {"minContains", "maxContains", "dependencies", "id"}
)
_WRONG = [5, -1, 1.5, True, None, "x", "", [], [1], [{}], [[]], {}, {"a": 5}, {"a": []}, [None]]


class TestMalformedSchemas:
    @pytest.mark.parametrize("draft", list(_DRAFTS))
    def test_a_schema_holding_wrong_shapes_is_refused_or_compiled_never_crashed(self, draft):
        # Each reader takes the document from a server it does not control: a value of the
        # wrong shape anywhere must give `Unsupported`, never another exception.
        rng = random.Random(f"malformed:{draft}")
        for _ in range(1500):
            schema = {k: rng.choice(_WRONG) for k in rng.sample(_KEYWORDS, rng.randint(1, 3))}
            if rng.random() < 0.3:
                schema = {"type": "object", "properties": {"p": schema}}
            if _DRAFTS[draft]:
                schema = {"$schema": _DRAFTS[draft], **schema}
            readers = (
                lambda s=schema: compile_schema(s),
                lambda s=schema: tool({"name": "t", "inputSchema": s, "outputSchema": s}),
                lambda s=schema: task({"name": "t", "inputs": s, "goal": s}),
            )
            for read in readers:
                with contextlib.suppress(Unsupported):
                    read()

    @pytest.mark.parametrize(
        ("schema", "keyword"),
        [
            ({"type": {}}, "type"),
            ({"additionalProperties": {}, "properties": True}, "properties"),
            ({"contains": {}, "minContains": "x"}, "minContains"),
            ({"contains": {}, "maxContains": -1}, "maxContains"),
            ({"$ref": 5}, "$ref"),
            ({"$schema": _DRAFTS["7"], "allOf": 5}, "allOf"),
            ({"$schema": _DRAFTS["7"], "dependencies": 5}, "dependencies"),
            ({"$schema": _DRAFTS["4"], "minimum": 1, "exclusiveMinimum": 5}, "exclusiveMinimum"),
        ],
    )
    def test_the_refusal_names_the_keyword(self, schema, keyword):
        with pytest.raises(Unsupported, match=keyword.replace("$", r"\$")):
            compile_schema(schema)


class TestDeepSchemas:
    @pytest.mark.parametrize(
        "wrap",
        [
            lambda s: {"allOf": [s]},
            lambda s: {"anyOf": [s, {"type": "null"}]},
            lambda s: {"not": s},
            lambda s: {"items": s},
            lambda s: {"properties": {"a": s}},
        ],
        ids=["allOf", "anyOf", "not", "items", "properties"],
    )
    def test_a_schema_nested_past_valgebras_depth_is_refused(self, wrap):
        schema = {"type": "string"}
        for _ in range(5000):
            schema = wrap(schema)
        with pytest.raises(Unsupported, match="nests past"):
            compile_schema(schema)
        with pytest.raises(Unsupported, match="nests past"):
            upgrade({"$schema": _DRAFTS["7"], **schema})

    def test_a_chain_of_references_compiled_in_place_past_the_limit_is_refused(self):
        # The document is three levels deep; the compiled set nests 300 deep.
        defs: dict[str, object] = {
            f"d{i}": {"allOf": [{"$ref": f"#/$defs/d{i + 1}"}]} for i in range(300)
        }
        defs["d300"] = {"type": "string"}
        with pytest.raises(Unsupported, match="nests past"):
            compile_schema({"$defs": defs, "$ref": "#/$defs/d0"})

    def test_a_constant_nested_past_the_bound_is_refused(self):
        value: object = 1
        for _ in range(1000):
            value = [value]
        with pytest.raises(Unsupported, match="nests past"):
            compile_schema({"const": value})


def test_a_pointer_index_is_written_as_rfc_6901_writes_it():
    listed = {"$defs": {"l": [{"type": "string"}, {"type": "integer"}]}}
    assert compile_schema({**listed, "$ref": "#/$defs/l/1"}).is_valid(1)
    for index in ("01", "+1", "\u0661", "\u00b2"):
        with pytest.raises(Unsupported, match="names nothing"):
            compile_schema({**listed, "$ref": f"#/$defs/l/{index}"})


def test_json_key_equates_one_and_one_point_zero_but_not_true():
    assert json_key([1, {"a": 2.0}]) == json_key([1.0, {"a": 2}])
    assert json_key(1) != json_key(True)


@pytest.mark.parametrize("key", ["minLength", "maxLength", "minItems", "maxItems"])
def test_an_integral_float_count_is_its_integer_and_leaves_the_integer_intact(key):
    # 7.0 and 7 are one number; reading 7.0 must not change what a later 7 compiles to.
    as_float = compile_schema({key: 7.0})
    as_int = compile_schema({key: 7})
    for value in ("x" * 6, "x" * 7, "x" * 8, [0] * 6, [0] * 7, [0] * 8):
        assert as_float.is_valid(value) == as_int.is_valid(value)


def test_an_integral_float_is_read_alike_by_integral_and_fractional_steps():
    value = float(3 * 2**70)
    assert compile_schema({"multipleOf": 3}).is_valid(value)
    assert compile_schema({"multipleOf": 1.5}).is_valid(value)
    assert compile_schema({"multipleOf": 0.0001}).is_valid(0.0075)


def test_a_schema_past_valgebras_nesting_limit_is_refused_not_raised():
    schema = {"type": "string"}
    for _ in range(80):
        schema = {"properties": {"a": schema}}
    with pytest.raises(Unsupported, match="valgebra refuses"):
        compile_schema(schema)


def test_a_property_name_with_a_lone_surrogate_is_refused():
    with pytest.raises(Unsupported, match="lone surrogate"):
        compile_schema({"properties": {"\ud800": {}}})


def test_a_draft_07_document_compiles_only_through_upgrade():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "definitions": {"s": {"type": "string"}},
        "properties": {"x": {"$ref": "#/definitions/s", "maxLength": 1}},
    }
    with pytest.raises(Unsupported, match="through `upgrade`"):
        Compiler(schema).compile(schema)
    assert compile_schema(schema).is_valid({"x": "abc"})


def test_two_hundred_definitions_compile_in_place():
    # Each fixpoint is a valgebra definition, and a set admits 128.
    schema = {
        "type": "object",
        "$defs": {f"d{i}": {"type": "string", "pattern": f"^d{i}_$"} for i in range(200)},
        "properties": {f"p{i}": {"$ref": f"#/$defs/d{i}"} for i in range(200)},
    }
    s = compile_schema(schema)
    assert s.is_valid({"p7": "d7_"})
    assert not s.is_valid({"p7": "d8_"})


def test_a_reference_that_reaches_itself_is_a_fixpoint():
    item = {"$ref": "#/$defs/tree"}
    tree = {"type": "object", "properties": {"kids": {"type": "array", "items": item}}}
    s = compile_schema({"$defs": {"tree": tree}, "$ref": "#/$defs/tree"})
    assert s.is_valid({"kids": [{"kids": []}]})
    assert not s.is_valid({"kids": [{"kids": [1]}]})


#: A recursive schema reached through `patternProperties`, whose check is a callback run at
#: membership time, outside every fixpoint's builder.
_PATTERNED = {
    "type": "object",
    "patternProperties": {"^[a-z]": {"$ref": "#/$defs/h"}},
    "additionalProperties": False,
}
_TREE = {"$defs": {"h": {"oneOf": [{"type": "number"}, _PATTERNED]}}, "$ref": "#/$defs/h"}


class TestRecursionThroughCallbacks:
    @pytest.mark.parametrize(
        ("value", "admitted"),
        [({"k": 1}, True), ({"k": {"j": 2}}, True), ({"k": "x"}, False), ({"K": 1}, False)],
    )
    def test_a_pattern_property_reaching_its_fixpoint_checks_the_fixpoint(self, value, admitted):
        assert compile_schema(_TREE).is_valid(value) is admitted

    def test_a_set_built_inside_a_fixpoint_is_not_reused_outside_it(self):
        c = Compiler(_TREE)
        c.ref("#/$defs/h")
        assert c.compile(_PATTERNED).is_valid({"k": 1})


@pytest.mark.parametrize(
    "schema",
    [
        {"required": "ab"},
        {"enum": "ab"},
        {"exclusiveMinimum": True},
        {"type": []},
        {"type": ["string", "string"]},
        {"multipleOf": 0},
        {"pattern": 5},
        {"properties": {"a": 3}},
        {"allOf": []},
        {"dependentRequired": {"a": "b"}},
    ],
)
def test_a_keyword_holding_what_the_meta_schema_refuses_is_refused(schema):
    with pytest.raises(Unsupported):
        compile_schema(schema)


def test_a_pointer_through_an_embedded_resource_is_refused():
    schema = {
        "$defs": {
            "z": {"type": "string"},
            "x": {
                "$id": "http://example.com/x.json",
                "$defs": {"z": {"type": "integer"}, "y": {"$ref": "#/$defs/z"}},
            },
        },
        "$ref": "#/$defs/x/$defs/y",
    }
    with pytest.raises(Unsupported, match="embedded"):
        compile_schema(schema)


class TestEcmaDialect:
    @pytest.mark.parametrize(
        ("pattern", "text", "admitted"),
        [
            (r"^\d$", "١", False),
            (r"^\d$", "7", True),
            (r"^\w$", "é", False),
            (r"^\s$", "﻿", True),
            (r"^\s$", "\u0085", False),
            (r"^.$", " ", False),
            (r"^[\d]$", "١", False),
            (r"^[^\d]$", "١", True),
            (r"^\cJ$", "\n", True),
            (r"^abc$", "abc\n", False),
            (r"a\b", "aé", True),
            (r"a\B", "aé", False),
            (r"\bfoo\b", "afoo", False),
            (r"^[\b]$", "\x08", True),
            (r"^[\s\S]$", "\n", True),
            (r"^[a\D]$", "x", True),
            (r"^[a\D]$", "7", False),
            (r"^[^]$", "\n", True),
            (r"^[]$", "", False),
            (r"^[a&&b]$", "&", True),
            (r"^[a~~b]$", "~", True),
            (r"^[a[]$", "[", True),
            (r"^a\0b$", "a\x00b", True),
            # A range from `-`, and a `^` after a negated shorthand: valgebra's class syntax
            # reads both apart from ECMA-262, so every class atom is written as a code point.
            (r"^[--a]$", ".", True),
            (r"^[^--z]$", ".", False),
            (r"^[\D^_]$", "0", False),
            (r"^[\D^_]$", "^", True),
            (r"^[^a\S]$", " ", True),
            (r"^[^a\S]$", "x", False),
            (r"^\uD83D\uDE00$", "\U0001f600", True),
            (r"^\u{1F600}$", "\U0001f600", True),
            (r"^\p{digit}+$", "\u0663", True),
            (r"^\p{sc=Grek}$", "\u03b1", True),
            # Annex B's literals, read as the character as every dialect reads them.
            (r"^a\:b$", "a:b", True),
            (r"^PUBMED:\{d}$", "PUBMED:{d}", True),
            (r"^x]$", "x]", True),
            (r"^a{b$", "a{b", True),
        ],
    )
    def test_a_pattern_means_what_ecma_262_says(self, pattern, text, admitted):
        assert compile_schema({"pattern": pattern}).is_valid(text) is admitted

    @pytest.mark.parametrize(
        "pattern",
        [
            r"\A",
            r"\z",
            r"\a",
            r"\x{41}",
            r"\U00000041",
            r"\pL",
            r"\p{Greek}",
            r"\p{lu}",
            r"(?i)a",
            r"(?P<n>a)",
            r"a**",
            r"a{1}{2}",
            r"^*",
            r"a{,3}",
            r"x{2,1}",
            r"[\d-z]",
            r"[z-a]",
            r"a)|(b",
            r"(a",
            "a\\",
        ],
    )
    def test_a_pattern_ecma_262_refuses_under_u_is_refused(self, pattern):
        # Each reads differently in valgebra's engine, Annex B or Python's `re`: `\A` is an
        # anchor to one and the letter to another, and `a)|(b` would close the group the
        # search wraps the pattern in.
        with pytest.raises(Unsupported, match="ECMA-262 refuses"):
            compile_schema({"pattern": pattern})


class TestDraft7:
    def test_an_items_array_is_a_prefix_and_additional_items_its_tail(self):
        s = compile_schema(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "items": [{"type": "integer"}],
                "additionalItems": {"type": "string"},
            }
        )
        assert s.is_valid([1, "a", "b"])
        assert not s.is_valid([1, 2])

    def test_dependencies_split_by_kind(self):
        s = compile_schema(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "dependencies": {"a": ["b"], "c": {"required": ["d"]}},
            }
        )
        assert not s.is_valid({"a": 1})
        assert not s.is_valid({"c": 1})
        assert s.is_valid({"a": 1, "b": 2, "c": 3, "d": 4})

    def test_a_ref_overrides_its_siblings(self):
        s = compile_schema(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "definitions": {"i": {"type": "integer"}},
                "properties": {"x": {"$ref": "#/definitions/i", "maximum": 0}},
            }
        )
        assert s.is_valid({"x": 5})

    def test_a_property_named_like_a_keyword_is_a_name(self):
        s = compile_schema(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "properties": {"items": {"type": "array"}, "dependencies": {"type": "string"}},
            }
        )
        assert s.is_valid({"items": [], "dependencies": "x"})
        assert not s.is_valid({"items": 1})

    @pytest.mark.parametrize(
        ("keywords", "value"),
        [
            ({"contains": {"const": 1}, "minContains": 2}, [1]),
            ({"prefixItems": [{"type": "string"}]}, [1]),
            ({"dependentRequired": {"a": ["b"]}}, {"a": 1}),
            ({"dependentSchemas": {"a": False}}, {"a": 1}),
        ],
    )
    def test_a_keyword_a_later_draft_added_asserts_nothing(self, keywords, value):
        schema = {"$schema": "http://json-schema.org/draft-07/schema#", **keywords}
        assert compile_schema(schema).is_valid(value)

    def test_a_ref_keeps_the_defs_beside_it(self):
        s = compile_schema(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "$defs": {"i": {"type": "integer"}},
                "$ref": "#/$defs/i",
            }
        )
        assert s.is_valid(1)
        assert not s.is_valid("a")


class TestOlderDrafts:
    D4 = "http://json-schema.org/draft-04/schema#"
    D6 = "http://json-schema.org/draft-06/schema#"

    def test_draft_04_exclusive_flags_move_onto_their_bound(self):
        s = compile_schema({"$schema": self.D4, "minimum": 1, "exclusiveMinimum": True})
        assert not s.is_valid(1)
        assert s.is_valid(2)
        assert compile_schema(
            {"$schema": self.D4, "maximum": 1, "exclusiveMaximum": False}
        ).is_valid(1)

    def test_draft_04_names_its_root_id_without_a_dollar(self):
        assert compile_schema(
            {"$schema": self.D4, "id": "http://x.example/s", "type": "string"}
        ).is_valid("a")

    @pytest.mark.parametrize(
        ("draft", "keywords", "value"),
        [
            (D4, {"const": 1}, 2),
            (D4, {"contains": {"const": 1}}, [2]),
            (D4, {"propertyNames": {"maxLength": 1}}, {"long": 1}),
            (D6, {"if": {"const": 1}, "then": False}, 1),
        ],
    )
    def test_a_keyword_the_draft_does_not_know_asserts_nothing(self, draft, keywords, value):
        assert compile_schema({"$schema": draft, **keywords}).is_valid(value)


def test_an_unknown_keyword_is_an_annotation_and_recorded():
    compiler = Compiler({"type": "string", "x-label": "id", "nullable": True})
    s = compiler.compile({"type": "string", "x-label": "id", "nullable": True})
    assert s.is_valid("a")
    assert not s.is_valid(None)
    assert compiler.ignored == {"x-label", "nullable"}


def test_a_nullable_number_keeps_its_non_integral_part():
    # The non-integral numbers inside `null | number` hold 0.5, met with the universe or not.
    nullable = compile_schema({"anyOf": [{"type": "null"}, {"type": "number"}]})
    number, integer = compile_schema({"type": "number"}), compile_schema({"type": "integer"})
    meet = intersection(number, complement(integer), nullable)
    assert meet.is_valid(0.5)
    assert not meet.is_empty()
    assert not intersection(meet, JSON).is_empty()
