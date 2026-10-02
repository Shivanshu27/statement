"""Static HTML scorecards: one file, no server, readable in light and dark."""

from __future__ import annotations

import html
from typing import Any

from statement.evaluate.score import DocScore

_CSS = """
:root{--bg:#fbfbfd;--fg:#16181d;--mute:#5d6470;--line:#e3e6ec;--card:#fff;
--good:#13795b;--warn:#a15c00;--bad:#b42318;--accent:#4f46e5}
@media (prefers-color-scheme:dark){:root{--bg:#111318;--fg:#e8eaf0;--mute:#9aa3b2;
--line:#2a2f3a;--card:#181b22;--good:#3ccf9a;--warn:#f0b35a;--bad:#ff7a6e;--accent:#a5a1ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:32px 0 10px;
text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}
.sub{color:var(--mute);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.tile .k{font-size:12px;color:var(--mute)}.tile .v{font-size:26px;font-weight:650;margin-top:2px}
.tile.head{border-color:var(--accent)}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;color:var(--mute);font-size:12px}td.n{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}code{font-size:12px}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:600;border:1px solid}
details{margin:2px 0}summary{cursor:pointer}
"""


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _verdict_pill(v: str) -> str:
    cls = {"ACCEPTED": "good", "NEEDS_REVIEW": "warn", "REJECTED": "bad"}[v]
    return f'<span class="pill {cls}">{html.escape(v)}</span>'


def render_html(card: dict[str, Any], scores: list[DocScore], title: str) -> str:
    o = card["overall"]
    m = card["manifest"]
    sw_cls = "good" if o["silent_wrong"] == 0 else "bad"
    tiles = [
        (
            "Silent-wrong (headline)",
            f'<span class="{sw_cls}">{o["silent_wrong"]}</span>',
            "head",
        ),
        ("Coverage (outcome only)", _pct(o["coverage"]), ""),
        ("Row agreement", _pct(o["row_agreement"]), ""),
        ("Exact documents", f"{o['exact_docs']} / {o['docs']}", ""),
        (
            "Tier 1 / Tier 2 accepted",
            f"{o['tier1_accepted']} / {o['tier2_accepted']}",
            "",
        ),
        ("Tokens in / out", f"{o['tokens_in']:,} / {o['tokens_out']:,}", ""),
    ]
    tile_html = "".join(
        f'<div class="tile {c}"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v, c in tiles
    )
    layout_rows = "".join(
        f"<tr><td><code>{html.escape(name)}</code></td><td class=n>{s['docs']}</td>"
        f"<td class=n>{_pct(s['coverage'])}</td><td class=n>{s['silent_wrong']}</td>"
        f"<td class=n>{_pct(s['row_agreement'])}</td><td class=n>{s['exact_docs']}</td>"
        f"<td class=n>{s['tier1_accepted']}/{s['tier2_accepted']}</td>"
        f"<td>{html.escape(', '.join(f'{k}×{v}' for k, v in list(s['reasons'].items())[:3]))}</td></tr>"
        for name, s in card["by_layout"].items()
    )
    order = {"ACCEPTED": 2, "NEEDS_REVIEW": 1, "REJECTED": 0}
    worst = sorted(
        scores, key=lambda s: (not s.silent_wrong, s.exact, order[s.verdict], s.name)
    )
    doc_rows = []
    for s in worst[:60]:
        diffs = "".join(
            f"<div><code>seq {d.seq} {html.escape(d.field)}</code>: "
            f"truth <code>{html.escape(d.truth)}</code> got <code>{html.escape(d.got)}</code></div>"
            for d in s.first_diffs
        )
        flag = ' <span class="pill bad">SILENT WRONG</span>' if s.silent_wrong else ""
        doc_rows.append(
            f"<tr><td><code>{html.escape(s.name)}</code>{flag}</td><td>{_verdict_pill(s.verdict)}</td>"
            f"<td class=n>{s.tier}</td><td class=n>{s.agreed}/{s.truth_rows}</td>"
            f"<td>{html.escape(', '.join(s.reasons)) or '—'}"
            f"{f'<details><summary>diffs</summary>{diffs}</details>' if diffs else ''}</td></tr>"
        )
    manifest = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td><code>{html.escape(str(v))}</code></td></tr>"
        for k, v in m.items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>
<h1>{html.escape(title)}</h1>
<div class="sub">Silent-wrong = ACCEPTED but disagrees with ground truth. Coverage is reported, never optimised.</div>
<div class="tiles">{tile_html}</div>
<h2>By layout</h2><div class="wrap"><table><tr><th>layout</th><th>docs</th><th>coverage</th>
<th>silent-wrong</th><th>row agreement</th><th>exact</th><th>T1/T2</th><th>top reasons</th></tr>
{layout_rows}</table></div>
<h2>Documents (worst first)</h2><div class="wrap"><table><tr><th>document</th><th>verdict</th>
<th>tier</th><th>rows agreed</th><th>reasons</th></tr>{"".join(doc_rows)}</table></div>
<h2>Run manifest</h2><div class="wrap"><table>{manifest}</table></div>
</main></body></html>"""


def render_corruption_html(
    rows: list[tuple[str, int, int, int, bool]], manifest: dict[str, Any]
) -> str:
    body = "".join(
        f"<tr><td><code>{html.escape(code)}</code></td><td class=n>{applied}</td>"
        f"<td class=n>{detected}</td><td class=n>{_pct(detected / applied if applied else 0)}</td>"
        f"<td>{'detectable' if expected else '<span class=warn>expected escape (L3 only)</span>'}</td></tr>"
        for code, applied, detected, _bc, expected in rows
    )
    man = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td><code>{html.escape(str(v))}</code></td></tr>"
        for k, v in manifest.items()
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Corruption detection</title><style>{_CSS}</style></head><body><main>
<h1>H1 · Corruption detection</h1>
<div class="sub">One failure from the catalogue applied to a correct statement; does the verifier notice?</div>
<h2>By failure mode</h2><div class="wrap"><table><tr><th>failure</th><th>applied</th><th>detected</th>
<th>rate</th><th>class</th></tr>{body}</table></div>
<h2>Run manifest</h2><div class="wrap"><table>{man}</table></div></main></body></html>"""
