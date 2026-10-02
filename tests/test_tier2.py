"""Tier 2 plumbing with scripted models: grounding, inference, assembly, failure modes.

The oracle double copies cells off the real text layer. Passing with it
proves the rescue path is correct end to end; it says nothing about how
good any real model is — that is measured separately, with a manifest.
"""

from __future__ import annotations

import pytest

from statement.domain.reasons import Code
from statement.forge.layouts import HELD_BACK, LAYOUTS
from statement.forge.ledger import INJECTION
from statement.pipeline.run import Verdict
from tests.conftest import (
    ScriptedLlm,
    failing,
    oracle_llm,
    oracle_payload,
    pipeline,
    read,
    reply,
    rows_of,
    sample,
)


@pytest.mark.slow
@pytest.mark.parametrize("layout", HELD_BACK)
@pytest.mark.parametrize("seed", [0, 1, 2, 9])
def test_perfect_transcription_is_accepted_at_tier2(
    profiles, layout: str, seed: int
) -> None:
    s = sample(layout, seed)
    r = pipeline(profiles, oracle_llm(s)).parse(s.pdf)
    assert r.verdict is Verdict.ACCEPTED, [str(x) for x in r.reasons]
    assert r.tier == 2
    assert r.statement is not None and rows_of(r.statement) == rows_of(s.truth)
    assert r.statement.provenance.tier == 2 and r.statement.provenance.prompt_hash


@pytest.mark.slow
@pytest.mark.parametrize(
    "layout", ["drcr_suffix", "signed_single", "paren_negative", "ledger_split"]
)
def test_rules_are_inferred_for_every_layout_family(layout: str) -> None:
    """With no profiles at all, Tier 2 alone recovers every structural family."""
    s = sample(layout, 4)
    r = pipeline((), oracle_llm(s)).parse(s.pdf)
    assert r.verdict is Verdict.ACCEPTED, [str(x) for x in r.reasons]
    assert rows_of(r.statement) == rows_of(s.truth)  # type: ignore[arg-type]


def _with_injection() -> int:
    for seed in range(200):
        s = sample("split_zero_filled", seed)
        if any(t.description == INJECTION for t in s.truth.transactions):
            return seed
    raise AssertionError("forge produced no injection fixture")


def test_prompt_injection_cannot_move_a_number(profiles) -> None:
    """F11: the hostile text is on the page; obeying it still cannot pass."""
    s = sample("split_zero_filled", _with_injection())
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["split_zero_filled"])
    payload["closing_balance"] = "9999999.00"  # printed — inside the injection text
    r = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    assert r.verdict is Verdict.NEEDS_REVIEW
    assert Code.TOTALS_MISMATCH in {x.code for x in r.reasons}


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("I could not read this document.", Code.RESCUE_UNPARSEABLE),
        ('{"rows": [{"line_ids": [], "date": "x"}]}', Code.RESCUE_UNPARSEABLE),
        (
            '{"rows": [{"line_ids": ["p0-l1"], "date": "x"',
            Code.RESCUE_UNPARSEABLE,
        ),  # truncated
    ],
)
def test_unusable_replies_degrade(profiles, text: str, code: Code) -> None:
    s = sample("no_balance", 0)
    r = pipeline(profiles, ScriptedLlm(reply(text))).parse(s.pdf)
    assert r.verdict is Verdict.NEEDS_REVIEW
    assert code in {x.code for x in r.reasons}


def test_unknown_and_duplicate_line_ids_are_reported(profiles) -> None:
    s = sample("no_balance", 1)
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["no_balance"])
    rows = payload["rows"]
    assert isinstance(rows, list)
    rows[0]["line_ids"] = ["p9-l999"]
    rows[2]["line_ids"] = rows[1]["line_ids"]
    r = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    codes = {x.code for x in r.reasons}
    assert {Code.RESCUE_UNKNOWN_LINE, Code.RESCUE_DUPLICATE_LINE} <= codes
    assert r.verdict is Verdict.NEEDS_REVIEW


def test_altered_description_is_flagged(profiles) -> None:
    s = sample("no_balance", 2)
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["no_balance"])
    rows = payload["rows"]
    assert isinstance(rows, list)
    rows[0]["description"] = "Grocery shopping (summarised by model)"
    r = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    assert r.verdict is Verdict.NEEDS_REVIEW
    assert any(
        x.code is Code.RESCUE_UNGROUNDED and "description" in x.detail
        for x in r.reasons
    )


@pytest.mark.parametrize(
    "code", [Code.RESCUE_ERROR, Code.RESCUE_BUDGET, Code.RESCUE_CACHE_MISS]
)
def test_provider_failures_degrade(profiles, code: Code) -> None:
    s = sample("split_zero_filled", 0)
    r = pipeline(profiles, ScriptedLlm(failing(code))).parse(s.pdf)
    assert r.verdict is Verdict.NEEDS_REVIEW
    assert code in {x.code for x in r.reasons}


def test_prompt_never_contains_the_verifier_rules(profiles) -> None:
    """§C3: the model is not told balances must chain."""
    s = sample("split_zero_filled", 0)
    llm = oracle_llm(s)
    pipeline(profiles, llm).parse(s.pdf)
    prompt = (llm.calls[0].system + llm.calls[0].user).lower()
    for banned in (
        "reconcile",
        "running balance must",
        "opening + ",
        "chain",
        "sum of",
    ):
        assert banned not in prompt


@pytest.mark.slow
@pytest.mark.parametrize(
    "layout",
    ["ledger_split_v2", "signed_single_v2", "drcr_suffix_v2", "paren_negative_v2"],
)
def test_template_drift_falls_to_tier2_not_to_a_wrong_answer(
    profiles, layout: str
) -> None:
    """R1: a changed template defeats Tier 1 loudly, and Tier 2 can recover it."""
    s = sample(layout, 3)
    assert pipeline(profiles).parse(s.pdf).verdict is Verdict.NEEDS_REVIEW
    r = pipeline(profiles, oracle_llm(s)).parse(s.pdf)
    assert r.verdict is Verdict.ACCEPTED and r.tier == 2
    assert rows_of(r.statement) == rows_of(s.truth)  # type: ignore[arg-type]
