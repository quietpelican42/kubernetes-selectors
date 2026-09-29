from __future__ import annotations

import time

import pytest

from kubernetes_selectors import (
    SelectorError,
    escape_field_value,
    everything,
    format_label_selector,
    label_selector_as_map,
    label_selector_as_selector,
    matches,
    new_requirement,
    nothing,
    parse_field_selector,
    parse_selector,
    parse_to_label_selector,
    selector_from_set,
    set_as_label_selector,
    unescape_field_value,
    validate_label_key,
    validate_label_value,
)


def test_canonical_string_sorts_requirements_and_values() -> None:
    assert str(parse_selector("b = 1, a in (z, y, y), !c")) == "a in (y,z),b=1,!c"
    assert str(parse_selector("x in (foo,,baz),y,z notin ()")) == "x in (,baz,foo),y,z notin ()"


def test_keywords_are_valid_keys_and_values() -> None:
    assert str(parse_selector("in in (in)")) == "in in (in)"
    assert str(parse_selector("notin=notin")) == "notin=notin"


def test_error_text_matches_apimachinery() -> None:
    with pytest.raises(SelectorError) as e:
        parse_selector("a in (b")
    assert str(e.value) == "unable to parse requirement: found '', expected: ',' or ')'"
    with pytest.raises(SelectorError) as e2:
        parse_selector("=b")
    assert str(e2.value) == "found '=', expected: !, identifier, or 'end of string'"
    with pytest.raises(SelectorError):
        parse_selector("a=b c")


def test_matching_semantics() -> None:
    assert matches("", {})
    assert matches("a!=b", {})
    assert matches("a notin (b)", {})
    assert not matches("a=b", {})
    assert not matches("!a", {"a": ""})
    assert matches("a>1", {"a": "2"})
    assert not matches("a<1", {"a": "x"})
    assert not matches("a>1", {"a": "1_0"})  # Go's ParseInt base 10 rejects underscores


@pytest.mark.parametrize("s", ["app=web", "app!=web", "app in (a,b)", "app notin (a)", "app", "!app", "a==b", "a="])
def test_valid_selectors_never_raise(s: str) -> None:
    parse_selector(s)


def test_selector_from_set_and_exact_match() -> None:
    s = selector_from_set({"b": "2", "a": "1"})
    assert str(s) == "a=1,b=2"
    assert s.requires_exact_match("a") == "1"
    assert s.requires_exact_match("z") is None
    assert selector_from_set(None).empty()


def test_nothing_and_everything() -> None:
    assert not nothing().matches({})
    assert not nothing().empty()
    assert everything().matches({"a": "b"})


def test_new_requirement_keeps_caller_order() -> None:
    r = new_requirement("k", "in", ["b", "a", "a"])
    assert r.values_unsorted() == ["b", "a", "a"]
    assert r.values() == ["a", "b"]
    assert str(r) == "k in (a,a,b)"
    with pytest.raises(SelectorError) as e:
        new_requirement("k", "in", None)
    assert str(e.value) == "values: Invalid value: null: for 'in', 'notin' operators, values set can't be empty"


def test_validators_return_go_strings() -> None:
    assert validate_label_key("app") == []
    assert validate_label_value("") == []
    assert validate_label_value("x" * 64)[0] == "must be no more than 63 bytes"
    assert validate_label_key("/a")[0] == "prefix part must be non-empty"
    assert validate_label_value("ok\n") != []  # a trailing newline is not accepted


def test_long_adversarial_input_is_linear() -> None:
    start = time.monotonic()
    validate_label_key("a" * 200000 + "!/x")
    validate_label_key("a." * 100000 + "!")
    assert time.monotonic() - start < 1.0


def test_label_selector_conversion() -> None:
    s = label_selector_as_selector(
        {
            "matchLabels": {"app": "web"},
            "matchExpressions": [
                {"key": "tier", "operator": "In", "values": ["b", "a"]},
                {"key": "x", "operator": "DoesNotExist"},
            ],
        }
    )
    assert str(s) == "app=web,tier in (a,b),!x"
    assert not label_selector_as_selector(None).matches({})
    assert label_selector_as_selector({}).matches({})
    with pytest.raises(SelectorError) as e:
        label_selector_as_selector({"matchExpressions": [{"key": "a", "operator": "Gt", "values": ["1"]}]})
    assert str(e.value) == '"Gt" is not a valid label selector operator'
    with pytest.raises(SelectorError) as e2:
        label_selector_as_selector({"matchExpressions": [{"key": "a", "operator": "In", "values": []}]})
    assert str(e2.value) == "values: Invalid value: null: for 'in', 'notin' operators, values set can't be empty"


def test_reverse_direction() -> None:
    assert parse_to_label_selector("a=1,b in (y,x),!c") == {
        "matchLabels": {"a": "1"},
        "matchExpressions": [
            {"key": "b", "operator": "In", "values": ["x", "y"]},
            {"key": "c", "operator": "DoesNotExist", "values": []},
        ],
    }
    assert label_selector_as_map(
        {"matchLabels": {"a": "1"}, "matchExpressions": [{"key": "b", "operator": "In", "values": ["2"]}]}
    ) == {"a": "1", "b": "2"}
    assert set_as_label_selector({"a": "1"}) == {"matchLabels": {"a": "1"}}
    assert format_label_selector({}) == "<none>"
    assert format_label_selector({"matchLabels": {"-": "x"}}) == "<error>"


def test_field_selector_parse_sort_escape() -> None:
    s = parse_field_selector("status.phase!=Failed,metadata.name==a\\,b")
    assert str(s) == "metadata.name=a\\,b,status.phase!=Failed"
    assert s.matches({"metadata.name": "a,b", "status.phase": "Running"})
    assert s.matches({"metadata.name": "a,b"})  # a missing field reads as ""
    assert parse_field_selector("a=").matches({})
    assert parse_field_selector("=").empty()


def test_field_selector_errors() -> None:
    with pytest.raises(SelectorError) as e:
        parse_field_selector("a")
    assert str(e.value) == "invalid selector: 'a'; can't understand 'a'"
    with pytest.raises(SelectorError) as e2:
        parse_field_selector("a=b=c")
    assert str(e2.value) == "invalid field selector: unescaped character in value: 61"
    with pytest.raises(SelectorError) as e3:
        parse_field_selector("a=\\x")
    assert str(e3.value) == "invalid field selector: invalid escape sequence: \\x"


def test_escape_round_trip() -> None:
    v = "a,b=c\\d"
    assert unescape_field_value(escape_field_value(v)) == v
