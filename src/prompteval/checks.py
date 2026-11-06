"""Deterministic checks that grade a model response.

Each check takes the response text and the check's settings and returns a
CheckResult. Checks are plain functions registered by name, so adding one is a
few lines.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CheckResult:
    kind: str
    passed: bool
    detail: str


CheckFn = Callable[[str, dict[str, Any]], tuple[bool, str]]
REGISTRY: dict[str, CheckFn] = {}


def check(name: str):
    def register(fn: CheckFn) -> CheckFn:
        REGISTRY[name] = fn
        return fn

    return register


def _norm(text: str, spec: dict[str, Any]) -> str:
    return text if spec.get("case_sensitive") else text.lower()


@check("equals")
def _equals(text, spec):
    want = str(spec["value"]).strip()
    got = text.strip()
    ok = _norm(got, spec) == _norm(want, spec)
    return ok, f"expected exactly {want!r}" if not ok else "exact match"


@check("contains")
def _contains(text, spec):
    values = spec["value"] if isinstance(spec["value"], list) else [spec["value"]]
    missing = [v for v in values if _norm(str(v), spec) not in _norm(text, spec)]
    return not missing, f"missing {missing}" if missing else f"found {values}"


@check("not_contains")
def _not_contains(text, spec):
    values = spec["value"] if isinstance(spec["value"], list) else [spec["value"]]
    present = [v for v in values if _norm(str(v), spec) in _norm(text, spec)]
    return not present, f"should not contain {present}" if present else "clean"


@check("regex")
def _regex(text, spec):
    flags = 0 if spec.get("case_sensitive") else re.IGNORECASE
    ok = re.search(spec["value"], text, flags | re.MULTILINE) is not None
    return ok, f"pattern {spec['value']!r} {'matched' if ok else 'not found'}"


@check("one_of")
def _one_of(text, spec):
    options = [str(o) for o in spec["value"]]
    got = text.strip().strip(".").strip()
    ok = _norm(got, spec) in {_norm(o, spec) for o in options}
    return ok, f"{got!r} is {'' if ok else 'not '}one of {options}"


@check("max_words")
def _max_words(text, spec):
    n = len(text.split())
    limit = int(spec["value"])
    return n <= limit, f"{n} words (limit {limit})"


def extract_json(text: str) -> Any:
    """Parse JSON from a response, allowing a fenced ```json block around it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return json.loads(fenced.group(1) if fenced else text)


@check("json_valid")
def _json_valid(text, spec):
    try:
        extract_json(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return False, f"invalid JSON: {exc.msg if hasattr(exc, 'msg') else exc}"
    return True, "valid JSON"


def _lookup(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, list):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data[part]
        else:
            raise KeyError(part)
    return data


@check("json_field")
def _json_field(text, spec):
    """Check one field of a JSON response. `path` uses dots, e.g. 'items.0.sku'."""
    try:
        value = _lookup(extract_json(text), spec["path"])
    except (json.JSONDecodeError, ValueError):
        return False, "response is not JSON"
    except (KeyError, IndexError, TypeError):
        return False, f"no field at {spec['path']!r}"
    if "value" in spec:
        ok = value == spec["value"]
        return ok, f"{spec['path']} = {value!r}" + ("" if ok else f", expected {spec['value']!r}")
    if "max_words" in spec:
        n = len(str(value).split())
        ok = n <= int(spec["max_words"])
        return ok, f"{spec['path']} has {n} words (limit {spec['max_words']})"
    if "one_of" in spec:
        ok = value in spec["one_of"]
        return ok, f"{spec['path']} = {value!r}" + ("" if ok else f", expected one of {spec['one_of']}")
    return True, f"{spec['path']} present"


def run_check(text: str, spec: dict[str, Any]) -> CheckResult:
    kind = spec.get("type")
    if kind not in REGISTRY:
        raise ValueError(f"Unknown check type {kind!r}. Known types: {', '.join(sorted(REGISTRY))}.")
    passed, detail = REGISTRY[kind](text, spec)
    return CheckResult(kind, passed, detail)
