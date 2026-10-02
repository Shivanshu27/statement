"""The scorer: LCS alignment, silent-wrong, coverage as outcome only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from statement.domain.model import Direction
from statement.evaluate.score import lcs_pairs, score_doc, summarise
from statement.pipeline.run import ParseResult, Verdict
from tests.conftest import sample


def test_identical_rows_are_not_double_counted() -> None:
    tea = (date(2026, 1, 2).isoformat(), Decimal("10.00"), Direction.DEBIT)
    other = (date(2026, 1, 2).isoformat(), Decimal("99.00"), Direction.DEBIT)
    # Truth has two identical teas; the extraction found one.
    assert len(lcs_pairs([tea, tea, other], [tea, other])) == 2


def test_accepted_but_wrong_is_silent_wrong() -> None:
    s = sample("ledger_split", 0)
    t0 = s.truth.transactions[0]
    wrong = s.truth.model_copy(
        update={
            "transactions": (
                t0.model_copy(update={"description": "SOMETHING ELSE"}),
                *s.truth.transactions[1:],
            )
        }
    )
    r = ParseResult(s.truth.doc_id, Verdict.ACCEPTED, wrong, (), 1, "ledger_split")
    sc = score_doc("x", "ledger_split", s.truth, r)
    assert sc.silent_wrong and not sc.exact
    assert sc.first_diffs[0].field == "description"


def test_needs_review_is_never_silent_wrong() -> None:
    s = sample("ledger_split", 0)
    r = ParseResult(s.truth.doc_id, Verdict.NEEDS_REVIEW, None, (), 1, None)
    sc = score_doc("x", "ledger_split", s.truth, r)
    assert not sc.silent_wrong
    summary = summarise([sc])
    assert summary.coverage == 0.0 and summary.silent_wrong_rate == 0.0
