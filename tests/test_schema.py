import pytest
from valgebra import complement, intersection, nothing

from valplan.schema import Compiler, Unsupported, compile_schema, json_key


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
            {"properties": {"a": {"$id": "x", "type": "string"}}},
            {"properties": {"opt?": {"type": "string"}}},
        ],
    )
    def test_it_refuses_what_it_cannot_translate(self, schema):
        with pytest.raises(Unsupported):
            compile_schema(schema)

    def test_it_refuses_a_draft_it_does_not_read(self):
        with pytest.raises(Unsupported, match="2020-12, 07, 06 and 04"):
            compile_schema({"$schema": "https://json-schema.org/draft/2019-09/schema"})


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
        ],
    )
    def test_a_pattern_means_what_ecma_262_says(self, pattern, text, admitted):
        assert compile_schema({"pattern": pattern}).is_valid(text) is admitted

    def test_a_negated_class_holding_a_negated_shorthand_is_refused(self):
        with pytest.raises(Unsupported, match="negated shorthand"):
            compile_schema({"pattern": r"[^a\S]"})


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
    # valgebra 0.0.20 proves `fractions & (None | number) & JSON` empty although it holds
    # 0.5; the compiler meets the universe only where a keyword's guard escapes it.
    nullable = compile_schema({"anyOf": [{"type": "null"}, {"type": "number"}]})
    number, integer = compile_schema({"type": "number"}), compile_schema({"type": "integer"})
    meet = intersection(number, complement(integer), nullable)
    assert meet.is_valid(0.5)
    assert not meet.is_empty()
