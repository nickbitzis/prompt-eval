"""Render a run as Markdown, a self-contained HTML page, or JSON."""

from __future__ import annotations

import html
import json

from .runner import RunResult


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}"


def to_markdown(run: RunResult) -> str:
    s = run.suite
    lines = [f"# Eval report: {s.name}", ""]
    if s.description:
        lines += [s.description, ""]
    lines += [f"Model `{s.model}` via `{run.provider}`. {len(s.cases)} cases x {len(s.prompts)} prompts.", ""]

    lines += ["## Summary", "", "| Prompt | Pass rate | Mean check score | Avg latency | Tokens in / out | Cost |", "|---|---|---|---|---|---|"]
    best = run.best_prompt()
    for p in run.summaries():
        name = f"**{p.prompt_id}** (best)" if p.prompt_id == best else p.prompt_id
        latency = f"{p.mean_latency_s:.2f}s" if p.mean_latency_s else "n/a"
        tokens = f"{p.input_tokens:,} / {p.output_tokens:,}" if p.output_tokens else "n/a"
        lines.append(f"| {name} | {p.passed}/{p.cases} ({p.pass_rate:.0%}) | {p.mean_score:.0%} | {latency} | {tokens} | {_money(p.cost_usd)} |")
    lines.append("")

    ids = [p.id for p in s.prompts]
    if len(ids) > 1:
        lines += ["## Regressions", ""]
        found = False
        for cand in ids[1:]:
            regs = run.regressions(ids[0], cand)
            if regs:
                found = True
                lines.append(f"- `{cand}` fails {len(regs)} case(s) that `{ids[0]}` passes: {', '.join(regs)}")
        if not found:
            lines.append(f"- None. No prompt fails a case that `{ids[0]}` passes.")
        lines.append("")

    lines += ["## Case matrix", "", "| Case | " + " | ".join(ids) + " |", "|---|" + "---|" * len(ids)]
    for case in s.cases:
        cells = []
        for pid in ids:
            r = next((x for x in run.results if x.prompt_id == pid and x.case_id == case.id), None)
            cells.append("skipped" if r is None else ("pass" if r.passed else f"FAIL ({r.score:.0%})"))
        lines.append(f"| {case.id} | " + " | ".join(cells) + " |")
    lines.append("")

    failures = [r for r in run.results if not r.passed]
    if failures:
        lines += ["## Failures", ""]
        for r in failures:
            lines.append(f"### {r.key}")
            if r.error:
                lines.append(f"- error: {r.error}")
            for c in r.checks:
                if not c.passed:
                    lines.append(f"- `{c.kind}`: {c.detail}")
            if r.completion:
                snippet = r.completion.text.strip().replace("\n", " ")
                lines.append(f"- response: {snippet[:200]}{'...' if len(snippet) > 200 else ''}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_json(run: RunResult) -> str:
    return json.dumps(
        {
            "suite": run.suite.name,
            "model": run.suite.model,
            "provider": run.provider,
            "summaries": [{**p.__dict__, "pass_rate": p.pass_rate} for p in run.summaries()],
            "results": [
                {
                    "prompt": r.prompt_id,
                    "case": r.case_id,
                    "passed": r.passed,
                    "score": r.score,
                    "error": r.error,
                    "checks": [c.__dict__ for c in r.checks],
                    "response": r.completion.text if r.completion else None,
                }
                for r in run.results
            ],
        },
        indent=2,
    )


_CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--text:#1c2330;--muted:#5d6878;--border:#dde2e9;--good:#1a7f37;--good-soft:#e6f4ea;--bad:#b3261e;--bad-soft:#fdecea;--bar:#2a78d6;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#11151c;--panel:#181e27;--text:#e6eaf0;--muted:#9aa5b5;--border:#2a3340;--good:#7ee2a0;--good-soft:#173322;--bad:#f2a29b;--bad-soft:#3a1f1d;--bar:#3987e5;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.05rem;margin:28px 0 10px}
.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px}
.card .big{font-size:1.8rem;font-weight:700;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--border);border-radius:4px;overflow:hidden;margin:8px 0}
.bar span{display:block;height:100%;background:var(--bar);border-radius:4px}
.best{font-size:.75rem;border:1px solid var(--border);border-radius:999px;padding:1px 8px;margin-left:6px;color:var(--muted)}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--border);border-radius:10px}
th,td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;font-size:.9rem;vertical-align:top}
th{color:var(--muted);font-weight:500}
.pass{background:var(--good-soft);color:var(--good)}.fail{background:var(--bad-soft);color:var(--bad)}
details{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:8px}
summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);padding:10px;border-radius:6px;font-size:.82rem}
"""


def to_html(run: RunResult) -> str:
    s = run.suite
    e = html.escape
    best = run.best_prompt()
    cards = []
    for p in run.summaries():
        tag = '<span class="best">best</span>' if p.prompt_id == best else ""
        cards.append(
            f'<div class="card"><div><strong>{e(p.prompt_id)}</strong>{tag}</div>'
            f'<div class="big">{p.pass_rate:.0%}</div><div class="bar"><span style="width:{p.pass_rate * 100:.1f}%"></span></div>'
            f'<div class="muted">{p.passed}/{p.cases} cases pass, mean check score {p.mean_score:.0%}<br>'
            + (f"{p.mean_latency_s:.2f}s avg latency, cost {_money(p.cost_usd)}" if p.output_tokens else "replayed responses, no usage data")
            + "</div></div>"
        )
    ids = [p.id for p in s.prompts]
    rows = []
    for case in s.cases:
        cells = []
        for pid in ids:
            r = next((x for x in run.results if x.prompt_id == pid and x.case_id == case.id), None)
            if r is None:
                cells.append('<td class="muted">skipped</td>')
            elif r.passed:
                cells.append('<td class="pass">pass</td>')
            else:
                cells.append(f'<td class="fail">fail ({r.score:.0%})</td>')
        tags = f' <span class="muted">{e(", ".join(case.tags))}</span>' if case.tags else ""
        rows.append(f"<tr><td>{e(case.id)}{tags}</td>{''.join(cells)}</tr>")
    details = []
    for r in run.results:
        if r.passed:
            continue
        items = "".join(f"<li><code>{e(c.kind)}</code>: {e(c.detail)}</li>" for c in r.checks if not c.passed)
        if r.error:
            items = f"<li>error: {e(r.error)}</li>" + items
        text = e(r.completion.text) if r.completion else ""
        details.append(f"<details><summary>{e(r.key)}</summary><ul>{items}</ul><pre>{text}</pre></details>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eval report: {e(s.name)}</title><style>{_CSS}</style></head>
<body><main>
<h1>Eval report: {e(s.name)}</h1>
<p class="muted">{e(s.description)} Model <code>{e(s.model)}</code> via {e(run.provider)}. {len(s.cases)} cases x {len(s.prompts)} prompts.</p>
<h2>Prompts</h2><div class="cards">{''.join(cards)}</div>
<h2>Case matrix</h2><div class="table-wrap"><table><thead><tr><th>Case</th>{''.join(f'<th>{e(i)}</th>' for i in ids)}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Failures</h2>{''.join(details) or '<p class="muted">None.</p>'}
</main></body></html>
"""
