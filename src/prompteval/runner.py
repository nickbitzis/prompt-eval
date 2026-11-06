"""Run every prompt against every case and grade the responses."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .checks import CheckResult, run_check
from .providers import Completion, Provider
from .suite import Case, Prompt, Suite


@dataclass
class CaseResult:
    prompt_id: str
    case_id: str
    tags: list[str]
    completion: Completion | None
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def key(self) -> str:
        return f"{self.prompt_id}/{self.case_id}"

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    @property
    def score(self) -> float:
        """Share of checks passed, so near misses still show up."""
        if self.error or not self.checks:
            return 0.0
        return sum(c.passed for c in self.checks) / len(self.checks)


@dataclass
class PromptSummary:
    prompt_id: str
    cases: int
    passed: int
    mean_score: float
    input_tokens: int
    output_tokens: int
    mean_latency_s: float
    cost_usd: float | None

    @property
    def pass_rate(self) -> float:
        return self.passed / self.cases if self.cases else 0.0


@dataclass
class RunResult:
    suite: Suite
    provider: str
    results: list[CaseResult]

    def for_prompt(self, prompt_id: str) -> list[CaseResult]:
        return [r for r in self.results if r.prompt_id == prompt_id]

    def summaries(self) -> list[PromptSummary]:
        out = []
        for p in self.suite.prompts:
            rows = self.for_prompt(p.id)
            done = [r.completion for r in rows if r.completion]
            costs = [c.cost(self.suite.model) for c in done]
            out.append(
                PromptSummary(
                    prompt_id=p.id,
                    cases=len(rows),
                    passed=sum(r.passed for r in rows),
                    mean_score=sum(r.score for r in rows) / len(rows) if rows else 0.0,
                    input_tokens=sum(c.input_tokens for c in done),
                    output_tokens=sum(c.output_tokens for c in done),
                    mean_latency_s=sum(c.latency_s for c in done) / len(done) if done else 0.0,
                    cost_usd=None if not done or any(c is None for c in costs) or not any(c.output_tokens for c in done) else sum(costs),
                )
            )
        return out

    def best_prompt(self) -> str:
        return max(self.summaries(), key=lambda s: (s.pass_rate, s.mean_score)).prompt_id

    def regressions(self, baseline: str, candidate: str) -> list[str]:
        """Case ids that pass on the baseline prompt and fail on the candidate."""
        base = {r.case_id: r.passed for r in self.for_prompt(baseline)}
        return [r.case_id for r in self.for_prompt(candidate) if base.get(r.case_id) and not r.passed]


def _grade(suite: Suite, prompt: Prompt, case: Case, provider: Provider) -> CaseResult:
    result = CaseResult(prompt.id, case.id, case.tags, completion=None)
    try:
        completion = provider.complete(result.key, prompt.system, prompt.render(case.vars))
    except Exception as exc:  # one failed call should not sink the whole run
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    result.completion = completion
    if completion.stop_reason == "refusal":
        result.error = "model declined to answer"
        return result
    result.checks = [run_check(completion.text, spec) for spec in suite.checks_for(case)]
    return result


def run_suite(suite: Suite, provider: Provider, workers: int = 4, tags: set[str] | None = None) -> RunResult:
    cases = [c for c in suite.cases if not tags or tags & set(c.tags)]
    jobs = [(p, c) for p in suite.prompts for c in cases]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda job: _grade(suite, job[0], job[1], provider), jobs))
    return RunResult(suite, provider.name, results)
