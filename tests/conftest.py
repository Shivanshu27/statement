"""Shared fixtures. No test touches the network."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from statement.adapters.pdf_reader import PdfplumberReader
from statement.adapters.pdf_renderer import render_pdf
from statement.adapters.profiles_fs import DirectoryProfiles
from statement.domain.model import Statement
from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.profile import Profile
from statement.domain.reasons import Code, Reason
from statement.domain.text import TextDocument
from statement.forge.corpus import ForgeDoc, Split, build
from statement.forge.layouts import LAYOUTS, PROFILED, Layout
from statement.forge.plan import wrap
from statement.pipeline.run import Pipeline, doc_id_for
from statement.ports import LlmPort, LlmRequest, LlmResponse

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def all_profiles() -> tuple[Profile, ...]:
    return DirectoryProfiles(ROOT / "profiles").profiles()


@pytest.fixture(scope="session")
def profiles(all_profiles: tuple[Profile, ...]) -> tuple[Profile, ...]:
    """The four original profiles. Held-back layouts stay unknown to Tier 1,
    so tests can drive them through Tier 2 regardless of later onboarding."""
    return tuple(p for p in all_profiles if p.id in PROFILED)


@dataclass(frozen=True)
class Sample:
    doc: ForgeDoc
    pdf: bytes
    truth: Statement


def sample(layout: str, seed: int) -> Sample:
    d = build(layout, seed, Split.DEV)
    pdf = render_pdf(d.plan)
    return Sample(d, pdf, d.truth.model_copy(update={"doc_id": doc_id_for(pdf)}))


def read(pdf: bytes) -> TextDocument:
    out = PdfplumberReader().read(pdf, doc_id_for(pdf))
    assert isinstance(out, Ok)
    return out.value


def rows_of(s: Statement) -> list[tuple[object, ...]]:
    return [
        (t.posted, t.debit, t.credit, t.balance, t.description) for t in s.transactions
    ]


# ------------------------------------------------------------------ fake LLMs


class ScriptedLlm:
    """Returns whatever ``script`` produces for the request. Records calls."""

    def __init__(
        self,
        script: Callable[[LlmRequest], Outcome[LlmResponse]],
        model: str = "fake/scripted",
    ) -> None:
        self._script = script
        self._model = model
        self.calls: list[LlmRequest] = []

    @property
    def model_id(self) -> str:
        return self._model

    def complete(self, req: LlmRequest) -> Outcome[LlmResponse]:
        self.calls.append(req)
        return self._script(req)


def reply(
    payload: dict[str, object] | str,
) -> Callable[[LlmRequest], Outcome[LlmResponse]]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return lambda req: Ok(
        LlmResponse(
            text=text, model_id="fake/scripted", input_tokens=100, output_tokens=50
        )
    )


def failing(
    code: Code = Code.RESCUE_ERROR,
) -> Callable[[LlmRequest], Outcome[LlmResponse]]:
    return lambda req: Fail(Reason(code, "scripted failure"))


def oracle_payload(
    doc: TextDocument, truth: Statement, layout: Layout
) -> dict[str, object]:
    """What a perfect transcriber would return: cells copied from the page.

    Built from the layout's own formatters and located on the real text
    layer, so it exercises grounding, rule inference and assembly honestly.
    It is a test double, never a stand-in for a measured model.
    """
    lines = doc.lines()
    keys = [c.key for c in layout.cols]
    rows: list[dict[str, object]] = []
    cursor = 0
    width = layout.desc_width()
    for t in truth.transactions:
        cells = layout.cells(t, layout)
        date_text = cells.get("posted", "")
        needles = [
            v
            for k, v in cells.items()
            if v and k not in ("posted", "reference", "value_date")
        ]
        pieces = wrap(t.description, width)
        while cursor < len(lines):
            text = lines[cursor].text
            if pieces[0] in text and all(n in text for n in needles):
                break
            cursor += 1
        else:
            raise AssertionError(f"oracle could not find row {t.seq}")
        ids = [lines[cursor + k].line_id for k in range(len(pieces))]
        row: dict[str, object] = {
            "line_ids": ids,
            "date": date_text or layout.fmt_date(t.posted),
            "description": t.description,
            "balance": cells.get("balance"),
        }
        for k in ("debit", "credit", "amount"):
            if k in keys:
                row[k] = cells.get(k) or None
        rows.append(row)
        cursor += len(pieces)
    return {
        "currency": truth.currency,
        "period_start": layout.fmt_period_date(truth.period_start),
        "period_end": layout.fmt_period_date(truth.period_end),
        "opening_balance": layout.fmt_balance(truth.opening_balance),
        "closing_balance": layout.fmt_balance(truth.closing_balance),
        "rows": rows,
    }


def oracle_llm(s: Sample) -> ScriptedLlm:
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS[s.doc.layout])
    return ScriptedLlm(reply(payload))


def pipeline(profiles: tuple[Profile, ...], llm: LlmPort | None = None) -> Pipeline:
    return Pipeline(PdfplumberReader(), profiles, llm)
