"""Command line entry point: `prompteval run suite.toml`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .providers import ReplayProvider, default_provider, save_recording
from .report import to_html, to_json, to_markdown
from .runner import run_suite
from .suite import load_suite


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prompteval", description="Compare prompt versions against a suite of test cases.")
    p.add_argument("--version", action="version", version=f"prompteval {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and write a report")
    run.add_argument("suite", help="path to a suite .toml file")
    run.add_argument("--replay", metavar="FILE", help="use saved responses instead of calling the API")
    run.add_argument("--record", metavar="FILE", help="save live responses so the run can be replayed")
    run.add_argument("--model", help="override the model named in the suite")
    run.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="effort level for the model")
    run.add_argument("--tag", action="append", help="only run cases with this tag. Repeatable.")
    run.add_argument("--workers", type=int, default=4, help="parallel requests, default 4")
    run.add_argument("--out", default="reports", help="folder for report.md, report.html, results.json")
    run.add_argument("--min-pass-rate", type=float, default=0.0, help="exit 1 if the best prompt is below this rate (0 to 1)")

    check = sub.add_parser("validate", help="check a suite file without running it")
    check.add_argument("suite")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        suite = load_suite(args.suite)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print(f"ok: {suite.name} has {len(suite.prompts)} prompts and {len(suite.cases)} cases")
        return 0

    if args.model:
        suite = type(suite)(**{**suite.__dict__, "model": args.model})
    provider = ReplayProvider(args.replay) if args.replay else default_provider(suite.model, suite.max_tokens, args.effort)
    run = run_suite(suite, provider, workers=args.workers, tags=set(args.tag or []))

    if args.record and not args.replay:
        save_recording(args.record, {r.key: r.completion for r in run.results if r.completion})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(to_markdown(run))
    (out / "report.html").write_text(to_html(run))
    (out / "results.json").write_text(to_json(run))

    print(f"{suite.name}: {len(run.results)} results with {run.provider}")
    for s in run.summaries():
        print(f"  {s.prompt_id:<16} {s.passed:>3}/{s.cases:<3} pass ({s.pass_rate:.0%})  mean check score {s.mean_score:.0%}")
    print(f"Best prompt: {run.best_prompt()}. Reports written to {out}/")

    best = max(s.pass_rate for s in run.summaries())
    return 1 if best < args.min_pass_rate else 0


if __name__ == "__main__":
    raise SystemExit(main())
