"""Load an eval suite from a TOML file."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checks import REGISTRY

_VAR = re.compile(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    id: str
    template: str
    system: str = ""

    def render(self, variables: dict[str, Any]) -> str:
        def sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in variables:
                raise KeyError(f"Prompt {self.id!r} uses {{{{{name}}}}} but the case does not set it.")
            return str(variables[name])

        return _VAR.sub(sub, self.template)

    @property
    def variables(self) -> set[str]:
        return set(_VAR.findall(self.template))


@dataclass(frozen=True)
class Case:
    id: str
    vars: dict[str, Any]
    checks: list[dict[str, Any]]
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    model: str
    max_tokens: int
    prompts: list[Prompt]
    cases: list[Case]
    defaults: list[dict[str, Any]]

    def checks_for(self, case: Case) -> list[dict[str, Any]]:
        return [*self.defaults, *case.checks]


def load_suite(path: str | Path) -> Suite:
    data = tomllib.loads(Path(path).read_text())
    return parse_suite(data)


def parse_suite(data: dict[str, Any]) -> Suite:
    try:
        prompts = [Prompt(p["id"], p["template"], p.get("system", "")) for p in data["prompts"]]
        cases = [Case(c["id"], c.get("vars", {}), c.get("checks", []), c.get("tags", [])) for c in data["cases"]]
    except KeyError as exc:
        raise ValueError(f"Suite is missing a required field: {exc.args[0]}") from exc
    suite = Suite(
        name=data.get("name", "eval"),
        description=data.get("description", ""),
        model=data.get("model", "claude-opus-5-5"),
        max_tokens=int(data.get("max_tokens", 1024)),
        prompts=prompts,
        cases=cases,
        defaults=data.get("default_checks", []),
    )
    validate(suite)
    return suite


def validate(suite: Suite) -> None:
    problems = []
    for kind, items in (("prompt", suite.prompts), ("case", suite.cases)):
        ids = [i.id for i in items]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            problems.append(f"duplicate {kind} ids: {sorted(dupes)}")
    if not suite.prompts or not suite.cases:
        problems.append("a suite needs at least one prompt and one case")
    for case in suite.cases:
        for spec in suite.checks_for(case):
            if spec.get("type") not in REGISTRY:
                problems.append(f"case {case.id!r} has unknown check type {spec.get('type')!r}")
        for prompt in suite.prompts:
            missing = prompt.variables - set(case.vars)
            if missing:
                problems.append(f"case {case.id!r} does not set {sorted(missing)} used by prompt {prompt.id!r}")
    if problems:
        raise ValueError("Invalid suite:\n  - " + "\n  - ".join(problems))
