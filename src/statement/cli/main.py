"""``statement`` command line. The only user interface in v1 (§A3)."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from statement.adapters.pdf_renderer import render_pdf
from statement.cli.composition import Settings, build_pipeline, manifest
from statement.domain.model import Statement
from statement.evaluate import corrupt
from statement.evaluate.report import render_corruption_html, render_html
from statement.evaluate.score import DocScore, score_doc, scorecard
from statement.forge.corpus import Split, generate
from statement.pipeline.run import ParseResult, Pipeline, Verdict, doc_id_for

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)


class LlmChoice(StrEnum):
    NONE = "none"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


LlmOpt = Annotated[
    LlmChoice | None,
    typer.Option("--llm", help="Tier-2 provider (default: $STATEMENT_LLM or none)"),
]
CacheOpt = Annotated[
    str | None, typer.Option("--cache", help="live | record | replay (default replay)")
]
ProfilesOpt = Annotated[
    Path | None, typer.Option("--profiles", help="profile directory")
]


def _settings(
    llm: LlmChoice | None, cache: str | None, profiles: Path | None
) -> Settings:
    return Settings.from_env(
        llm=llm.value if llm else None, cache_mode=cache, profiles_dir=profiles
    )


# ------------------------------------------------------------------ forge


@app.command()
def forge(
    out: Annotated[Path, typer.Option(help="output directory")],
    split: Annotated[Split, typer.Option()] = Split.DEV,
    n: Annotated[int, typer.Option(help="documents per layout")] = 40,
    layouts: Annotated[
        str | None, typer.Option(help="comma-separated layout ids")
    ] = None,
) -> None:
    """Generate synthetic statements with exact ground truth."""
    secret = (
        os.environ.get("STATEMENT_HOLDOUT_SECRET") if split is Split.HOLDOUT else None
    )
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for d in generate(
        split, n, layouts=tuple(layouts.split(",")) if layouts else None, secret=secret
    ):
        pdf = render_pdf(d.plan)
        truth = d.truth.model_copy(update={"doc_id": doc_id_for(pdf)})
        (out / f"{d.name}.pdf").write_bytes(pdf)
        payload = {"meta": d.meta(), "statement": truth.model_dump(mode="json")}
        (out / f"{d.name}.truth.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8"
        )
        count += 1
    typer.echo(f"wrote {count} documents to {out}")


# ------------------------------------------------------------------ parse / explain


def _result_json(r: ParseResult) -> dict[str, Any]:
    return {
        "doc_id": r.doc_id,
        "verdict": r.verdict.value,
        "tier": r.tier,
        "profile": r.profile_id,
        "reasons": [str(x) for x in r.reasons],
        "checks": {k: v.value for k, v in r.checks.items()},
        "statement": r.statement.model_dump(mode="json") if r.statement else None,
    }


@app.command()
def parse(
    path: Path,
    allow_review: Annotated[
        bool, typer.Option(help="exit 0 for NEEDS_REVIEW too")
    ] = False,
    llm: LlmOpt = None,
    cache: CacheOpt = None,
    profiles: ProfilesOpt = None,
) -> None:
    """Parse one PDF. Prints JSON; exits non-zero unless ACCEPTED."""
    result = build_pipeline(_settings(llm, cache, profiles)).parse(path.read_bytes())
    typer.echo(json.dumps(_result_json(result), indent=2, ensure_ascii=False))
    if result.verdict is Verdict.ACCEPTED:
        return
    raise typer.Exit(
        0 if allow_review and result.verdict is Verdict.NEEDS_REVIEW else 2
    )


@app.command()
def explain(
    path: Path, llm: LlmOpt = None, cache: CacheOpt = None, profiles: ProfilesOpt = None
) -> None:
    """Show one document's climb up the trust ladder."""
    r = build_pipeline(_settings(llm, cache, profiles)).parse(path.read_bytes())
    typer.echo(f"{path.name}  doc_id {r.doc_id[:12]}")
    for e in r.trace:
        typer.echo(f"  {e.stage:<11} {e.outcome!s:<14} {e.ms:>8.2f} ms")
        for d in e.detail:
            typer.echo(f"  {'':<11} · {d}")
    rows = len(r.statement.transactions) if r.statement else 0
    typer.echo(f"  => {r.verdict.value} (tier {r.tier}, {rows} rows)")


# ------------------------------------------------------------------ evaluation

_WORKER: Pipeline | None = None


def _init_worker(settings: Settings) -> None:
    global _WORKER
    _WORKER = build_pipeline(settings)


def _parse_file(path: Path) -> tuple[str, ParseResult]:
    assert _WORKER is not None
    return path.name, _WORKER.parse(path.read_bytes())


def _load_truth(pdf: Path) -> tuple[str, Statement]:
    data = json.loads(
        pdf.with_suffix("").with_suffix(".truth.json").read_text(encoding="utf-8")
    )
    return str(data["meta"]["layout"]), Statement.model_validate(data["statement"])


def _run_corpus(
    settings: Settings, pdfs: list[Path], workers: int
) -> dict[str, ParseResult]:
    if workers <= 1:
        _init_worker(settings)
        return dict(_parse_file(p) for p in pdfs)
    # Documents are independent and CPU-bound: a process pool, never threads
    # sharing patched state (the runner thread-race trap, G5).
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_init_worker, initargs=(settings,)
    ) as ex:
        return dict(ex.map(_parse_file, pdfs, chunksize=4))


def _pdfs(corpus: Path) -> list[Path]:
    pdfs = sorted(corpus.glob("*.pdf"))
    if not pdfs:
        raise typer.BadParameter(f"no PDFs in {corpus}")
    return pdfs


def _run_dir(out: Path, label: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # Two runs in the same second must not collide (or overwrite each other).
    for n in range(1000):
        d = out / (f"{stamp}-{label}" if n == 0 else f"{stamp}-{label}-{n}")
        try:
            d.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return d
    raise RuntimeError(f"cannot allocate a run directory under {out}")


@app.command("eval")
def evaluate(
    corpus: Path,
    out: Annotated[Path, typer.Option()] = Path("runs"),
    workers: Annotated[int, typer.Option()] = max(1, (os.cpu_count() or 2) - 1),
    llm: LlmOpt = None,
    cache: CacheOpt = None,
    profiles: ProfilesOpt = None,
) -> None:
    """Score a corpus against ground truth; write scorecard.json/.html."""
    settings = _settings(llm, cache, profiles)
    pdfs = _pdfs(corpus)
    results = _run_corpus(settings, pdfs, workers)
    scores: list[DocScore] = []
    for pdf in pdfs:
        layout, truth = _load_truth(pdf)
        scores.append(score_doc(pdf.stem, layout, truth, results[pdf.name]))
    card = scorecard(scores, manifest(settings, corpus=corpus, files=pdfs))
    run = _run_dir(out, corpus.name)
    (run / "scorecard.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    with (run / "results.jsonl").open("w", encoding="utf-8") as f:
        for s in scores:
            f.write(
                json.dumps(
                    {
                        k: getattr(s, k)
                        for k in (
                            "name",
                            "layout",
                            "verdict",
                            "tier",
                            "agreed",
                            "truth_rows",
                            "exact",
                            "silent_wrong",
                            "reasons",
                        )
                    }
                )
                + "\n"
            )
    (run / "scorecard.html").write_text(
        render_html(card, scores, f"Scorecard · {corpus.name}"), encoding="utf-8"
    )
    o = card["overall"]
    typer.echo(
        f"{corpus.name}: {o['docs']} docs | silent-wrong {o['silent_wrong']} | "
        f"coverage {o['coverage']:.1%} | row agreement {o['row_agreement']:.1%} | "
        f"exact {o['exact_docs']}/{o['docs']} | T1/T2 {o['tier1_accepted']}/{o['tier2_accepted']}"
    )
    for name, s in card["by_layout"].items():
        typer.echo(
            f"  {name:<20} cov {s['coverage']:>6.1%}  sw {s['silent_wrong']}  rows {s['row_agreement']:>6.1%}"
        )
    typer.echo(f"report: {run / 'scorecard.html'}")


@app.command("eval-diff")
def eval_diff(a: Path, b: Path) -> None:
    """Metric deltas between two runs (directories or scorecard.json files)."""

    def load(p: Path) -> dict[str, Any]:
        f = p / "scorecard.json" if p.is_dir() else p
        return dict(json.loads(f.read_text(encoding="utf-8")))

    ca, cb = load(a), load(b)
    keys = (
        "docs",
        "accepted",
        "silent_wrong",
        "coverage",
        "row_agreement",
        "exact_docs",
        "tier2_accepted",
    )
    for scope in ["overall", *sorted(set(ca["by_layout"]) | set(cb["by_layout"]))]:
        sa = ca["overall"] if scope == "overall" else ca["by_layout"].get(scope, {})
        sb = cb["overall"] if scope == "overall" else cb["by_layout"].get(scope, {})
        cells = []
        for k in keys:
            va, vb = sa.get(k, 0), sb.get(k, 0)
            if va != vb:
                cells.append(f"{k} {va} -> {vb}")
        typer.echo(f"{scope:<20} {'; '.join(cells) or 'no change'}")


@app.command("corrupt-eval")
def corrupt_eval(
    corpus: Path,
    out: Annotated[Path, typer.Option()] = Path("runs"),
    trials: Annotated[int, typer.Option()] = 3,
) -> None:
    """H1: inject catalogue failures into truth statements; measure detection."""
    pdfs = _pdfs(corpus)
    truths = [_load_truth(p)[1] for p in pdfs]
    tallies = corrupt.run(truths, trials=trials)
    rows = [
        (code, t.applied, t.detected, t.by_construction, corrupt.MUTATIONS[code][1])
        for code, t in tallies.items()
    ]
    detectable = [r for r in rows if r[4]]
    det_applied = sum(r[1] for r in detectable)
    det_hit = sum(r[2] for r in detectable)
    settings = Settings.from_env()
    man = manifest(settings, corpus=corpus, files=pdfs, extra={"trials": trials})
    payload = {
        "manifest": man,
        "detectable_rate": round(det_hit / det_applied, 4) if det_applied else None,
        "by_failure": {
            c: {
                "applied": a,
                "detected": d,
                "by_construction": bc,
                "expected_detectable": e,
            }
            for c, a, d, bc, e in rows
        },
    }
    run = _run_dir(out, f"corrupt-{corpus.name}")
    (run / "corruption.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    (run / "corruption.html").write_text(
        render_corruption_html(rows, man), encoding="utf-8"
    )
    for code, applied, detected, _bc, expected in rows:
        rate = detected / applied if applied else 0
        typer.echo(
            f"  {code:<30} {detected:>5}/{applied:<5} {rate:>7.1%}  {'' if expected else '(expected escape)'}"
        )
    if det_applied:
        typer.echo(
            f"detectable classes: {det_hit}/{det_applied} = {det_hit / det_applied:.2%}"
        )
    typer.echo(f"report: {run / 'corruption.html'}")


@app.command()
def replay(
    corpus: Path,
    out: Annotated[Path, typer.Option(help="dump file")],
    llm: LlmOpt = None,
    profiles: ProfilesOpt = None,
) -> None:
    """Deterministic dump of every result, for byte-for-byte regression (§D4)."""
    settings = _settings(llm, "replay", profiles)
    pdfs = _pdfs(corpus)
    results = _run_corpus(settings, pdfs, 1)
    with out.open("w", encoding="utf-8") as f:
        for pdf in pdfs:
            f.write(
                json.dumps(
                    {"name": pdf.name, **_result_json(results[pdf.name])},
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            )
    typer.echo(f"wrote {len(pdfs)} results to {out}")


@app.command()
def canary(
    golden: Annotated[Path, typer.Argument(help="fixed golden PDFs")] = Path(
        "canary/golden"
    ),
    history: Annotated[Path, typer.Option(help="where daily observations live")] = Path(
        "canary/history"
    ),
    llm: LlmOpt = None,
) -> None:
    """Drift canary: re-read fixed pages live; diff against the last live run (H5)."""
    from statement.adapters.pdf_reader import PdfplumberReader
    from statement.cli.composition import build_llm
    from statement.domain.outcome import Fail
    from statement.evaluate.canary import compare, observe

    settings = _settings(llm, "live", None)
    model = build_llm(settings)
    if model is None:
        raise typer.BadParameter(
            "the canary needs a live model: --llm anthropic|ollama"
        )
    reader = PdfplumberReader()
    docs = []
    pdfs = _pdfs(golden)
    for pdf in pdfs:
        data = pdf.read_bytes()
        doc = reader.read(data, doc_id_for(data))
        if isinstance(doc, Fail):
            raise typer.BadParameter(f"{pdf.name}: {doc.reasons}")
        docs.append((pdf.stem, doc.value))
    observed = observe(docs, model)
    history.mkdir(parents=True, exist_ok=True)
    previous = sorted(history.glob("*.json"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    record = {
        "manifest": manifest(settings, corpus=golden, files=pdfs),
        "observed": observed,
    }
    (history / f"{stamp}.json").write_text(
        json.dumps(record, indent=1, sort_keys=True), encoding="utf-8"
    )
    if not previous:
        typer.echo(f"first observation recorded ({len(docs)} documents)")
        return
    last = json.loads(previous[-1].read_text(encoding="utf-8"))
    if (
        last["manifest"]["prompt_hash"] != record["manifest"]["prompt_hash"]
        or last["manifest"]["llm"] != record["manifest"]["llm"]
    ):
        typer.echo(
            "prompt or model changed since the last run: not comparable, new baseline recorded"
        )
        return
    changes = compare(last["observed"], observed)
    if not changes:
        typer.echo(f"no change across {len(docs)} documents since {previous[-1].stem}")
        return
    docs_changed = len({c.doc for c in changes})
    typer.echo(
        f"DRIFT: {len(changes)} cells changed in {docs_changed}/{len(docs)} documents since {previous[-1].stem}"
    )
    for c in changes[:40]:
        typer.echo(f"  {c.doc} {c.where}: {c.before!r} -> {c.after!r}")
    raise typer.Exit(1)


@app.command()
def profiles(profiles: ProfilesOpt = None) -> None:
    """Validate and list layout profiles."""
    from statement.cli.composition import load_profiles

    for p in load_profiles(Settings.from_env(profiles_dir=profiles)):
        typer.echo(f"{p.id:<20} v{p.version}  {p.description}")


def main() -> None:  # pragma: no cover
    sys.exit(app())
