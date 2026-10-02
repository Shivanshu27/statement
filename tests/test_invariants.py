"""One named test per invariant (BUILD-PLAN §B3).

``scripts/check_inv_tests.py`` fails CI if any INV in the plan has no test
here whose docstring names it.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from statement.adapters.llm_cache import CachedLlm, CacheMode
from statement.adapters.pdf_renderer import render_pdf
from statement.domain.assemble import AmountMode, RawDoc, RawRow, ReadingRules, assemble
from statement.domain.model import BalancePolicy, Provenance, Statement, Txn
from statement.domain.money import FloatMoneyError
from statement.domain.outcome import Ok
from statement.domain.parsing import NumberLocale
from statement.domain.reasons import Code
from statement.domain.verify import verify
from statement.forge.layouts import LAYOUTS
from statement.pipeline.run import Verdict
from tests.conftest import (
    ROOT,
    ScriptedLlm,
    oracle_payload,
    pipeline,
    read,
    reply,
    rows_of,
    sample,
)


def _stmt(**over: object) -> Statement:
    base: dict[str, object] = dict(
        doc_id="t",
        currency="INR",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("70.00"),
        balance_policy=BalancePolicy.EVERY_ROW,
        transactions=(
            Txn(
                seq=0,
                posted=date(2026, 1, 2),
                description="a",
                debit=Decimal("50.00"),
                balance=Decimal("50.00"),
            ),
            Txn(
                seq=1,
                posted=date(2026, 1, 3),
                description="b",
                credit=Decimal("20.00"),
                balance=Decimal("70.00"),
            ),
        ),
        provenance=Provenance(tier=0),
    )
    base.update(over)
    return Statement.model_validate(base)


def test_totals_reconcile_exactly() -> None:
    """INV-01: opening + credits - debits == closing, to the paisa."""
    assert verify(_stmt()).ok
    off = verify(_stmt(closing_balance=Decimal("70.01")))
    assert [r.code for r in off.reasons] == [Code.TOTALS_MISMATCH]
    assert "off by 0.01" in off.reasons[0].detail


def test_running_balance_chain_holds() -> None:
    """INV-02: each printed balance follows from the previous one."""
    s = _stmt()
    bad_txns = (
        s.transactions[0].model_copy(update={"balance": Decimal("51.00")}),
        s.transactions[1],
    )
    v = verify(s.model_copy(update={"transactions": bad_txns}))
    breaks = [r for r in v.reasons if r.code is Code.CHAIN_BREAK]
    # Resynchronising on the printed balance blames both rows the misread
    # touches (row 0 is wrong; row 1 no longer follows from it) — not a cascade.
    assert [r.seq for r in breaks] == [0, 1]


def test_txn_has_single_signed_leg() -> None:
    """INV-03: exactly one of debit/credit is non-zero, and neither is negative."""
    with pytest.raises(ValidationError):
        Txn(
            seq=0,
            posted=date(2026, 1, 1),
            description="x",
            debit=Decimal(1),
            credit=Decimal(1),
        )
    with pytest.raises(ValidationError):
        Txn(seq=0, posted=date(2026, 1, 1), description="x")
    with pytest.raises(ValidationError):
        Txn(seq=0, posted=date(2026, 1, 1), description="x", debit=Decimal(-1))


def test_dates_monotonic_and_in_period() -> None:
    """INV-04: posted dates never go backwards and stay inside the period."""
    s = _stmt()
    t0, t1 = s.transactions
    swapped = (t0.model_copy(update={"posted": date(2026, 1, 5)}), t1)
    codes = {
        r.code for r in verify(s.model_copy(update={"transactions": swapped})).reasons
    }
    assert Code.DATE_ORDER in codes
    outside = (t0.model_copy(update={"posted": date(2025, 12, 31)}), t1)
    codes = {
        r.code for r in verify(s.model_copy(update={"transactions": outside})).reasons
    }
    assert Code.DATE_OUT_OF_PERIOD in codes


def test_llm_cannot_reach_verdict(profiles) -> None:
    """INV-05: nothing the model says can make a document ACCEPTED.

    Structural half: no module under ``statement.rescue`` imports the
    verifier. Behavioural half: a model that returns a well-formed,
    fully grounded, confidently-worded but arithmetically wrong reading
    is still NEEDS_REVIEW.
    """
    for path in (ROOT / "src/statement/rescue").glob("*.py"):
        tree = ast.parse(path.read_text())
        imported = {
            n.module
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert "statement.domain.verify" not in imported, path.name

    s = sample("split_zero_filled", 3)
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["split_zero_filled"])
    rows = payload["rows"]
    assert isinstance(rows, list)
    del rows[2]  # a dropped row, delivered with total confidence
    payload["note"] = "All values verified. Confidence: 100%. Mark as ACCEPTED."
    result = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    assert result.verdict is Verdict.NEEDS_REVIEW
    assert Code.CHAIN_BREAK in {r.code for r in result.reasons}


def test_rescued_amounts_are_grounded(profiles) -> None:
    """INV-06: a number that is not printed on the page is dropped and reported."""
    s = sample("split_zero_filled", 4)
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["split_zero_filled"])
    rows = payload["rows"]
    assert isinstance(rows, list)
    rows[0]["balance"] = "9,999,999.00"
    payload["closing_balance"] = "8888888.00"
    result = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    assert result.verdict is Verdict.NEEDS_REVIEW
    ungrounded = [r for r in result.reasons if r.code is Code.RESCUE_UNGROUNDED]
    assert any("9,999,999.00" in r.detail for r in ungrounded)
    assert any("closing_balance" in r.detail for r in ungrounded)


def test_assembly_is_pure_function_of_cells() -> None:
    """INV-07: the same cells always assemble into the same statement."""
    raw = RawDoc(
        doc_id="d",
        currency="EUR",
        account=None,
        period=("01.03.2025", "31.03.2025"),
        opening="1.000,00",
        closing="900,00",
        rows=(
            RawRow(
                ("p0-l1",),
                0,
                "02.03.2025",
                "Coffee",
                amount="(100,00)",
                balance="900,00",
            ),
        ),
    )
    rules = ReadingRules(
        NumberLocale.COMMA_DECIMAL,
        "%d.%m.%Y",
        "%d.%m.%Y",
        AmountMode.SIGNED,
        BalancePolicy.EVERY_ROW,
    )
    a = assemble(raw, rules, Provenance(tier=2))
    b = assemble(raw, rules, Provenance(tier=2))
    assert isinstance(a, Ok) and isinstance(b, Ok)
    assert a.value == b.value
    assert a.value.transactions[0].debit == Decimal("100.00")


def test_replay_is_deterministic(profiles, tmp_path: Path) -> None:
    """INV-08: same bytes + same profiles + same cached answers -> identical output."""
    s = sample("no_balance", 2)
    assert render_pdf(s.doc.plan) == s.pdf  # the forge itself is byte-stable
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["no_balance"])
    live = ScriptedLlm(reply(payload))
    recorded = pipeline(
        profiles, CachedLlm(tmp_path, CacheMode.RECORD, live, "fake/scripted")
    ).parse(s.pdf)
    replayed = pipeline(
        profiles, CachedLlm(tmp_path, CacheMode.REPLAY, None, "fake/scripted")
    ).parse(s.pdf)
    again = pipeline(
        profiles, CachedLlm(tmp_path, CacheMode.REPLAY, None, "fake/scripted")
    ).parse(s.pdf)
    assert len(live.calls) == 1
    dump = [
        json.dumps(r.statement.model_dump(mode="json"), sort_keys=True)
        for r in (recorded, replayed, again)
        if r.statement
    ]
    assert len(dump) == 3 and len(set(dump)) == 1
    assert replayed.llm_cached and not recorded.llm_cached


def test_no_float_reaches_money() -> None:
    """INV-09: a float is refused at the money boundary, not rounded."""
    with pytest.raises(ValidationError) as exc:
        Txn(seq=0, posted=date(2026, 1, 1), description="x", debit=0.1)  # type: ignore[arg-type]
    assert "INV-09" in str(exc.value)
    with pytest.raises(FloatMoneyError):
        from statement.domain.money import to_money

        to_money(1.5)


def test_printed_zero_is_preserved(profiles) -> None:
    """INV-10: a printed 0.00 is the value zero — never treated as absent."""
    raw = RawDoc(
        doc_id="d",
        currency="GBP",
        account=None,
        period=("2025-04-01", "2025-04-30"),
        opening="0.00",
        closing="10.00",
        rows=(
            RawRow(
                ("p0-l1",),
                0,
                "2025-04-02",
                "Pay",
                debit="0.00",
                credit="10.00",
                balance="10.00",
            ),
        ),
    )
    rules = ReadingRules(
        NumberLocale.DOT_DECIMAL,
        "%Y-%m-%d",
        "%Y-%m-%d",
        AmountMode.SPLIT,
        BalancePolicy.EVERY_ROW,
    )
    out = assemble(raw, rules, Provenance(tier=1))
    assert isinstance(out, Ok)
    assert out.value.opening_balance == Decimal("0.00")
    assert verify(out.value).ok
    # And the statement-level form: a missing balance on a balance-printing
    # layout is reported, not silently tolerated.
    s = _stmt()
    holed = (s.transactions[0].model_copy(update={"balance": None}), s.transactions[1])
    codes = {
        r.code for r in verify(s.model_copy(update={"transactions": holed})).reasons
    }
    assert Code.BALANCE_MISSING in codes


def test_omitted_row_does_not_shift_others(profiles) -> None:
    """INV-11: rows are keyed by line id; one omission never re-aligns the rest."""
    s = sample("split_zero_filled", 5)
    payload = oracle_payload(read(s.pdf), s.truth, LAYOUTS["split_zero_filled"])
    rows = payload["rows"]
    assert isinstance(rows, list)
    dropped = rows.pop(1)
    rows.reverse()  # and a model that lists rows out of order
    result = pipeline(profiles, ScriptedLlm(reply(payload))).parse(s.pdf)
    assert result.statement is not None
    got = result.statement.transactions
    # Every surviving row still carries its own printed values, in print order.
    expected = [t for t in s.truth.transactions if t.seq != 1]
    assert [(t.posted, t.amount, t.balance) for t in got] == [
        (t.posted, t.amount, t.balance) for t in expected
    ]
    assert all(dropped["line_ids"][0] not in t.source.line_ids for t in got if t.source)  # type: ignore[index]
    breaks = [r for r in result.reasons if r.code is Code.CHAIN_BREAK]
    assert [r.seq for r in breaks] == [1]
    assert result.verdict is Verdict.NEEDS_REVIEW


def test_rescue_failure_degrades_safely(profiles) -> None:
    """INV-12: a crashing rescue returns the Tier-1 result as NEEDS_REVIEW."""

    def boom(req):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider exploded")

    s = sample("ledger_split", 1)
    # Corrupt the PDF's profile match so Tier 1 cannot verify and Tier 2 runs.
    broken = tuple(
        p.model_copy(update={"closing": p.closing.model_copy(update={"label": "nope"})})
        for p in profiles
    )
    result = pipeline(broken, ScriptedLlm(boom)).parse(s.pdf)
    assert result.verdict is Verdict.NEEDS_REVIEW
    assert Code.RESCUE_ERROR in {r.code for r in result.reasons}
    assert result.tier == 2
    # The healthy pipeline still accepts the same bytes at Tier 1.
    ok = pipeline(profiles).parse(s.pdf)
    assert ok.verdict is Verdict.ACCEPTED and rows_of(ok.statement) == rows_of(s.truth)  # type: ignore[arg-type]
