import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from prompteval.cli import main
from prompteval.providers import (
    ClaudeProvider,
    Completion,
    ReplayProvider,
    save_recording,
)
from prompteval.report import to_html, to_json, to_markdown
from prompteval.runner import run_suite
from prompteval.suite import load_suite

EXAMPLES = Path(__file__).parents[1] / "examples"


def example_run():
    suite = load_suite(EXAMPLES / "ticket_triage.toml")
    return run_suite(suite, ReplayProvider(EXAMPLES / "sample_responses.json"))


def test_example_scores():
    run = example_run()
    by_id = {s.prompt_id: s for s in run.summaries()}
    assert (by_id["v1-basic"].passed, by_id["v2-schema"].passed) == (1, 7)
    assert run.best_prompt() == "v2-schema"
    assert run.regressions("v1-basic", "v2-schema") == []
    assert run.regressions("v2-schema", "v1-basic") == ["double-charge", "export-crash", "dark-mode", "invoice-address", "angry-vague", "injection"]
    # Replayed text has no usage data, so cost is unknown rather than zero.
    assert by_id["v2-schema"].cost_usd is None


def test_tag_filter():
    suite = load_suite(EXAMPLES / "ticket_triage.toml")
    run = run_suite(suite, ReplayProvider(EXAMPLES / "sample_responses.json"), tags={"billing"})
    assert {r.case_id for r in run.results} == {"double-charge", "invoice-address"}


class Boom:
    name = "boom"

    def complete(self, key, system, user):
        if key.endswith("dark-mode"):
            raise TimeoutError("slow")
        if key.endswith("locked-out"):
            return Completion(text="", stop_reason="refusal")
        return Completion(text='{"category": "other", "priority": "p3", "summary": "x"}', input_tokens=100, output_tokens=20, latency_s=0.5)


def test_errors_and_refusals_fail_without_stopping_the_run():
    suite = load_suite(EXAMPLES / "ticket_triage.toml")
    run = run_suite(suite, Boom(), workers=2)
    assert len(run.results) == 16
    errors = {r.key: r.error for r in run.results if r.error}
    assert errors["v1-basic/dark-mode"] == "TimeoutError: slow"
    assert errors["v2-schema/locked-out"] == "model declined to answer"
    summary = run.summaries()[0]
    assert summary.cost_usd is not None and summary.cost_usd > 0
    # 7 responses: six at 0.5s and one refusal at 0s. The timed-out call has none.
    assert summary.mean_latency_s == pytest.approx(3 / 7)


def test_reports_render():
    run = example_run()
    md = to_markdown(run)
    assert "| **v2-schema** (best) | 7/8 (88%)" in md
    assert "### v1-basic/double-charge" in md
    page = to_html(run)
    assert page.startswith("<!doctype html>") and "v2-schema" in page and "<script" not in page
    data = json.loads(to_json(run))
    assert len(data["results"]) == 16


def test_html_escapes_model_output(tmp_path):
    suite = load_suite(EXAMPLES / "ticket_triage.toml")

    class Evil:
        name = "evil"

        def complete(self, key, system, user):
            return Completion(text="<script>alert(1)</script>")

    assert "<script>" not in to_html(run_suite(suite, Evil()))


def test_record_and_replay_roundtrip(tmp_path):
    path = tmp_path / "rec.json"
    save_recording(path, {"p/c": Completion(text="hi", input_tokens=3, output_tokens=1, latency_s=0.2)})
    assert ReplayProvider(path).complete("p/c", "", "") == Completion(text="hi", input_tokens=3, output_tokens=1, latency_s=0.2)


def test_claude_provider_builds_the_request():
    calls = []

    def create(**params):
        calls.append(params)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="hello")],
            usage=SimpleNamespace(input_tokens=12, output_tokens=3),
            stop_reason="end_turn",
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    provider = ClaudeProvider("claude-opus-5-5", max_tokens=200, effort="low", client=client)
    out = provider.complete("p/c", "Be brief.", "Hi")
    assert out.text == "hello" and out.input_tokens == 12
    params = calls[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["system"] == "Be brief."
    assert params["output_config"] == {"effort": "low"}
    assert params["fallbacks"] == "default"
    assert out.cost("claude-opus-5-5") == (12 * 4 + 3 * 20) / 1e6


def test_cli_replay(tmp_path, capsys):
    code = main(["run", str(EXAMPLES / "ticket_triage.toml"), "--replay", str(EXAMPLES / "sample_responses.json"), "--out", str(tmp_path), "--min-pass-rate", "0.8"])
    assert code == 0
    assert (tmp_path / "report.html").exists()
    assert "Best prompt: v2-schema" in capsys.readouterr().out
    assert main(["run", str(EXAMPLES / "ticket_triage.toml"), "--replay", str(EXAMPLES / "sample_responses.json"), "--out", str(tmp_path), "--min-pass-rate", "0.9"]) == 1


def test_cli_validate(capsys, tmp_path):
    assert main(["validate", str(EXAMPLES / "ticket_triage.toml")]) == 0
    bad = tmp_path / "bad.toml"
    bad.write_text('[[prompts]]\nid = "p"\ntemplate = "{{x}}"\n[[cases]]\nid = "c"\n')
    assert main(["validate", str(bad)]) == 2
