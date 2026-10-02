"""The invariant engine. The only thing that can make a document ACCEPTED.

INV-05 is structural: nothing on the LLM side imports this module
(import-linter contract), and the verdict function in ``pipeline`` takes only
this module's output. A model can make a document *look* right; only the
arithmetic here can make it accepted.

A bank statement checks itself — the running balance is a hash chain over
the transactions. That is the whole bet of the project (BUILD-PLAN §A1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from statement.domain.model import BalancePolicy, Statement
from statement.domain.reasons import Code, Reason


class Check(StrEnum):
    PASS = "pass"  # noqa: S105 - a check outcome, not a password
    FAIL = "fail"
    NOT_APPLICABLE = "n/a"


@dataclass(frozen=True, slots=True)
class Verification:
    reasons: tuple[Reason, ...]
    checks: dict[str, Check] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.reasons


def check_totals(stmt: Statement) -> list[Reason]:
    """INV-01: opening + Σcredit − Σdebit == closing, exactly."""
    credits = sum((t.credit for t in stmt.transactions), Decimal(0))
    debits = sum((t.debit for t in stmt.transactions), Decimal(0))
    expected = stmt.opening_balance + credits - debits
    if expected != stmt.closing_balance:
        delta = stmt.closing_balance - expected
        return [
            Reason(
                Code.TOTALS_MISMATCH,
                f"opening {stmt.opening_balance} + credits {credits} - debits "
                f"{debits} = {expected}, closing is {stmt.closing_balance} "
                f"(off by {delta})",
            )
        ]
    return []


def check_chain(stmt: Statement) -> list[Reason]:
    """INV-02: bal[i] == bal[i-1] + credit[i] − debit[i] for every printed balance.

    After a break the chain resynchronises on the printed balance, so one
    misread row produces one reason at the row that is actually wrong, not a
    cascade blaming every row after it.
    """
    reasons: list[Reason] = []
    prev = stmt.opening_balance
    for t in stmt.transactions:
        expected = prev + t.signed
        if t.balance is None:
            prev = expected
            continue
        if t.balance != expected:
            src = t.source.line_ids if t.source else ()
            reasons.append(
                Reason(
                    Code.CHAIN_BREAK,
                    f"expected balance {expected}, printed {t.balance}",
                    seq=t.seq,
                    line_ids=src,
                )
            )
        prev = t.balance
    return reasons


def check_balance_presence(stmt: Statement) -> list[Reason]:
    """INV-10, at statement level: a layout that prints balances prints them all.

    A missing balance on one row is how "0.00 read as absent" and partial
    reads surface. Mixed presence is never accepted.
    """
    if stmt.balance_policy is not BalancePolicy.EVERY_ROW:
        return []
    return [
        Reason(Code.BALANCE_MISSING, "row has no balance", seq=t.seq)
        for t in stmt.transactions
        if t.balance is None
    ]


def check_dates(stmt: Statement, tolerance_days: int = 0) -> list[Reason]:
    """INV-04: posted dates non-decreasing and inside the period (± tolerance)."""
    reasons: list[Reason] = []
    tol = timedelta(days=tolerance_days)
    lo, hi = stmt.period_start - tol, stmt.period_end + tol
    prev = None
    for t in stmt.transactions:
        if not lo <= t.posted <= hi:
            reasons.append(
                Reason(
                    Code.DATE_OUT_OF_PERIOD,
                    f"{t.posted} outside {stmt.period_start}..{stmt.period_end}",
                    seq=t.seq,
                )
            )
        if prev is not None and t.posted < prev:
            reasons.append(
                Reason(Code.DATE_ORDER, f"{t.posted} after {prev}", seq=t.seq)
            )
        prev = t.posted
    return reasons


def verify(stmt: Statement, *, tolerance_days: int = 0) -> Verification:
    checks: dict[str, Check] = {}
    reasons: list[Reason] = []

    if not stmt.transactions:
        reasons.append(Reason(Code.NO_ROWS, "no transactions extracted"))

    for name, found in (
        ("totals", check_totals(stmt)),
        ("dates", check_dates(stmt, tolerance_days)),
    ):
        checks[name] = Check.FAIL if found else Check.PASS
        reasons.extend(found)

    if stmt.balance_policy is BalancePolicy.EVERY_ROW:
        presence = check_balance_presence(stmt)
        chain = check_chain(stmt)
        checks["balance_presence"] = Check.FAIL if presence else Check.PASS
        checks["chain"] = Check.FAIL if chain else Check.PASS
        reasons.extend(presence)
        reasons.extend(chain)
    else:
        # Reduced trust (ADR-0014): only INV-01 constrains the amounts.
        checks["balance_presence"] = Check.NOT_APPLICABLE
        checks["chain"] = Check.NOT_APPLICABLE

    return Verification(reasons=tuple(reasons), checks=checks)
