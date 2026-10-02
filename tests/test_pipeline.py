"""Ingest limits and rejection paths (§F4): PDFs are untrusted input."""

from __future__ import annotations

from statement.adapters.pdf_reader import PdfplumberReader
from statement.adapters.pdf_renderer import render_pdf
from statement.domain.reasons import Code
from statement.forge.plan import PagePlan, RenderPlan, TextItem
from statement.pipeline.run import Limits, Pipeline, Verdict
from tests.conftest import pipeline, sample


def test_not_a_pdf_is_rejected(profiles) -> None:
    r = pipeline(profiles).parse(b"<html>hello</html>")
    assert r.verdict is Verdict.REJECTED and r.reasons[0].code is Code.NOT_PDF


def test_corrupt_pdf_is_rejected(profiles) -> None:
    r = pipeline(profiles).parse(b"%PDF-1.4\n garbage garbage")
    assert r.verdict is Verdict.REJECTED


def test_oversized_input_is_rejected_before_parsing(profiles) -> None:
    p = Pipeline(PdfplumberReader(), profiles, limits=Limits(max_bytes=1000))
    r = p.parse(sample("ledger_split", 0).pdf)
    assert r.verdict is Verdict.REJECTED and r.reasons[0].code is Code.TOO_LARGE


def test_page_bomb_is_rejected(profiles) -> None:
    plan = RenderPlan(
        pages=tuple(PagePlan((TextItem(36, 40, f"page {i}"),)) for i in range(60))
    )
    r = pipeline(profiles).parse(render_pdf(plan))
    assert r.verdict is Verdict.REJECTED and r.reasons[0].code is Code.TOO_MANY_PAGES


def test_no_text_layer_is_rejected(profiles) -> None:
    blank = render_pdf(RenderPlan(pages=(PagePlan(()),)))
    r = pipeline(profiles).parse(blank)
    assert r.verdict is Verdict.REJECTED and r.reasons[0].code is Code.NO_TEXT_LAYER


def test_explain_trace_covers_the_ladder(profiles) -> None:
    r = pipeline(profiles).parse(sample("drcr_suffix", 2).pdf)
    stages = [e.stage for e in r.trace]
    assert stages[:4] == ["ingest", "text_layer", "classify", "tier1"]
    assert "verify" in stages
