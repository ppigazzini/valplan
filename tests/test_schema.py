import pytest
from valgebra import intersection, nothing

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

    def test_a_fractional_step_is_checked_in_decimal_arithmetic(self):
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

    def test_it_refuses_another_draft(self):
        with pytest.raises(Unsupported, match="2020-12"):
            compile_schema({"$schema": "http://json-schema.org/draft-07/schema#"})


def test_json_key_equates_one_and_one_point_zero_but_not_true():
    assert json_key([1, {"a": 2.0}]) == json_key([1.0, {"a": 2}])
    assert json_key(1) != json_key(True)


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
        ],
    )
    def test_a_pattern_means_what_ecma_262_says(self, pattern, text, admitted):
        assert compile_schema({"pattern": pattern}).is_valid(text) is admitted
