from pathlib import Path

import pytest

from prompteval.suite import Prompt, load_suite, parse_suite

EXAMPLE = Path(__file__).parents[1] / "examples" / "ticket_triage.toml"


def minimal(**overrides):
    data = {
        "prompts": [{"id": "p", "template": "Say {{word}}"}],
        "cases": [{"id": "c", "vars": {"word": "hi"}, "checks": [{"type": "contains", "value": "hi"}]}],
    }
    data.update(overrides)
    return data


def test_example_suite_loads():
    suite = load_suite(EXAMPLE)
    assert suite.name == "ticket-triage"
    assert [p.id for p in suite.prompts] == ["v1-basic", "v2-schema"]
    assert len(suite.cases) == 8
    # Default checks are applied before case checks.
    assert suite.checks_for(suite.cases[0])[0]["type"] == "json_valid"


def test_render_fills_variables():
    p = Prompt("p", 'JSON like {"x": 1} for {{ name }}')
    assert p.render({"name": "Ada"}) == 'JSON like {"x": 1} for Ada'
    assert p.variables == {"name"}
    with pytest.raises(KeyError):
        p.render({})


def test_defaults():
    suite = parse_suite(minimal())
    assert suite.model == "claude-opus-5-5"
    assert suite.max_tokens == 1024


def test_missing_variable_is_reported():
    data = minimal(cases=[{"id": "c", "vars": {}}])
    with pytest.raises(ValueError, match=r"does not set \['word'\]"):
        parse_suite(data)


def test_duplicate_ids_and_bad_checks():
    data = minimal()
    data["prompts"].append({"id": "p", "template": "again {{word}}"})
    data["cases"][0]["checks"].append({"type": "nope"})
    with pytest.raises(ValueError) as exc:
        parse_suite(data)
    assert "duplicate prompt ids" in str(exc.value)
    assert "unknown check type 'nope'" in str(exc.value)


def test_missing_required_field():
    with pytest.raises(ValueError, match="template"):
        parse_suite({"prompts": [{"id": "p"}], "cases": []})
