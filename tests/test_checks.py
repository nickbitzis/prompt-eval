import pytest

from prompteval.checks import extract_json, run_check


def ok(text, **spec):
    return run_check(text, spec).passed


def test_equals_and_case():
    assert ok("  Yes ", type="equals", value="yes")
    assert not ok("Yes", type="equals", value="yes", case_sensitive=True)


def test_contains_list_and_not_contains():
    assert ok("refund issued for order 12", type="contains", value=["refund", "order"])
    result = run_check("refund issued", {"type": "contains", "value": ["refund", "credit"]})
    assert not result.passed and "credit" in result.detail
    assert ok("all good", type="not_contains", value="error")
    assert not ok("Error: bad", type="not_contains", value=["error"])


def test_regex_and_one_of():
    assert ok("Order #4412", type="regex", value=r"#\d{4}")
    assert ok("Billing.", type="one_of", value=["billing", "bug"])
    assert not ok("refunds", type="one_of", value=["billing", "bug"])


def test_max_words():
    assert ok("one two three", type="max_words", value=3)
    assert not ok("one two three four", type="max_words", value=3)


def test_extract_json_handles_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('{"a": [1, 2]}') == {"a": [1, 2]}


def test_json_valid():
    assert ok('{"a": 1}', type="json_valid")
    assert not ok("Category: billing", type="json_valid")


@pytest.mark.parametrize(
    "spec, passed",
    [
        ({"path": "a.b", "value": 2}, True),
        ({"path": "a.b", "value": 3}, False),
        ({"path": "items.1.sku", "value": "X2"}, True),
        ({"path": "items.5.sku"}, False),
        ({"path": "a.missing"}, False),
        ({"path": "a.b", "one_of": [1, 2]}, True),
        ({"path": "note", "max_words": 3}, True),
        ({"path": "note", "max_words": 2}, False),
    ],
)
def test_json_field(spec, passed):
    text = '{"a": {"b": 2}, "items": [{"sku": "X1"}, {"sku": "X2"}], "note": "three short words"}'
    assert ok(text, type="json_field", **spec) is passed


def test_json_field_on_prose():
    result = run_check("not json", {"type": "json_field", "path": "a"})
    assert not result.passed and result.detail == "response is not JSON"


def test_unknown_check_type():
    with pytest.raises(ValueError, match="Unknown check type"):
        run_check("x", {"type": "vibes"})
