"""Model providers. A provider turns (system, user message) into a Completion."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# USD per million tokens (input, output). Used only for the cost column.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    stop_reason: str = "end_turn"

    def cost(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        pin, pout = PRICES[model]
        return (self.input_tokens * pin + self.output_tokens * pout) / 1e6


class Provider(Protocol):
    name: str

    def complete(self, key: str, system: str, user: str) -> Completion: ...


class ClaudeProvider:
    """Calls the Claude Messages API with the official SDK.

    Credentials come from the environment (ANTHROPIC_API_KEY or an
    `ant auth login` profile). Nothing is read from or written to disk.
    """

    name = "claude"

    def __init__(self, model: str, max_tokens: int = 1024, effort: str | None = None, client=None):
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on install extras
                raise RuntimeError("Install the Claude extra first: uv sync --extra claude") from exc
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def complete(self, key: str, system: str, user: str) -> Completion:
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": user}],
            # If the primary model declines, the API retries on a suitable
            # fallback model inside the same call.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        if system:
            params["system"] = system
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        start = time.perf_counter()
        response = self.client.beta.messages.create(**params)
        latency = time.perf_counter() - start
        text = "".join(block.text for block in response.content if block.type == "text")
        return Completion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_s=latency,
            stop_reason=response.stop_reason or "",
        )


class ReplayProvider:
    """Serves saved responses from a JSON file keyed by 'prompt_id/case_id'.

    Use it to rerun checks offline, in CI, or after editing checks without
    paying for new model calls.
    """

    name = "replay"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.responses = json.loads(self.path.read_text())

    def complete(self, key: str, system: str, user: str) -> Completion:
        if key not in self.responses:
            raise KeyError(f"No saved response for {key!r} in {self.path}.")
        entry = self.responses[key]
        if isinstance(entry, str):
            return Completion(text=entry)
        return Completion(**entry)


def save_recording(path: str | Path, completions: dict[str, Completion]) -> None:
    data = {k: c.__dict__ for k, c in sorted(completions.items())}
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def default_provider(model: str, max_tokens: int, effort: str | None = None) -> Provider:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_PROFILE")):
        # The SDK can also use a saved `ant auth login` profile, so this is a
        # hint rather than a hard stop.
        print("note: no ANTHROPIC_API_KEY set, trying the default credential profile")
    return ClaudeProvider(model, max_tokens, effort)
