"""Raw printed cells -> ``Statement``, deterministically.

Both tiers end here. Tier 1 reads cells by profile geometry; Tier 2 gets
cells from an LLM. Neither builds the final object: this pure function does
(INV-07), so the same cells always produce the same statement and every
interpretation rule — signs, locales, year inference — exists exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import ValidationError

from statement.domain.model import BalancePolicy, Provenance, SourceSpan, Statement, Txn
from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.parsing import (
    Marker,
    NumberLocale,
    PrintedAmount,
    parse_amount,
    parse_date,
)
from statement.domain.reasons import Code, Reason
from statement.domain.text import norm_ws


class AmountMode(StrEnum):
    SPLIT = "split"  # separate debit and credit columns
    SIGNED = "signed"  # one column; minus (any spelling) means debit
    SUFFIX = "suffix"  # one column; Dr/Cr marker required


@dataclass(frozen=True, slots=True)
class RawRow:
    line_ids: tuple[str, ...]
    page: int
    posted: str
    description: str
    debit: str | None = None
    credit: str | None = None
    amount: str | None = None
    balance: str | None = None
    value_date: str | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class RawDoc:
    doc_id: str
    currency: str | None
    account: str | None
    period: tuple[str, str] | None
    opening: str | None
    closing: str | None
    rows: tuple[RawRow, ...]


@dataclass(frozen=True, slots=True)
class ReadingRules:
    """How to interpret raw cells: from a profile (Tier 1) or inferred (Tier 2)."""

    locale: NumberLocale
    period_format: str
    row_date_format: str
    amount_mode: AmountMode
    balance_policy: BalancePolicy


def _blank(raw: str | None) -> bool:
    return raw is None or not raw.strip()


def _signed_balance(p: PrintedAmount) -> Decimal:
    # Overdrawn balances print as "Dr", "-" or parentheses.
    if p.marker in (Marker.DR, Marker.MINUS):
        return -p.value
    return p.value


def _money(
    raw: str, rules: ReadingRules, what: str, seq: int | None
) -> Outcome[PrintedAmount]:
    out = parse_amount(raw, rules.locale)
    if isinstance(out, Fail):
        r = out.reasons[0]
        return Fail(Reason(r.code, f"{what}: {r.detail}", seq=seq))
    return out


def _legs(
    row: RawRow, rules: ReadingRules, seq: int
) -> Outcome[tuple[Decimal, Decimal]]:
    """Return (debit, credit) for a row according to the amount mode."""
    if rules.amount_mode is AmountMode.SPLIT:
        legs: list[Decimal] = []
        for what, raw in (("debit", row.debit), ("credit", row.credit)):
            if _blank(raw):
                legs.append(Decimal(0))
                continue
            assert raw is not None
            p = _money(raw, rules, what, seq)
            if isinstance(p, Fail):
                return p
            # A split column carries its direction in its position; any extra
            # sign marker is contradictory and gets refused, not reconciled.
            if p.value.marker not in (
                Marker.NONE,
                Marker.MINUS if what == "debit" else Marker.NONE,
            ):
                return Fail(
                    Reason(
                        Code.UNPARSEABLE_MONEY, f"{what} {raw!r} has a sign", seq=seq
                    )
                )
            legs.append(p.value.value)  # INV-10: a printed 0.00 is zero
        return Ok((legs[0], legs[1]))

    if _blank(row.amount):
        return Fail(Reason(Code.UNPARSEABLE_MONEY, "amount missing", seq=seq))
    assert row.amount is not None
    p = _money(row.amount, rules, "amount", seq)
    if isinstance(p, Fail):
        return p
    marker, value = p.value.marker, p.value.value
    if rules.amount_mode is AmountMode.SIGNED:
        if marker in (Marker.DR, Marker.CR):
            return Fail(
                Reason(
                    Code.UNPARSEABLE_MONEY,
                    f"Dr/Cr in signed column {row.amount!r}",
                    seq=seq,
                )
            )
        return Ok(
            (value, Decimal(0)) if marker is Marker.MINUS else (Decimal(0), value)
        )
    # SUFFIX
    if marker is Marker.DR:
        return Ok((value, Decimal(0)))
    if marker is Marker.CR:
        return Ok((Decimal(0), value))
    return Fail(
        Reason(Code.UNPARSEABLE_MONEY, f"no Dr/Cr marker on {row.amount!r}", seq=seq)
    )


def assemble(
    doc: RawDoc, rules: ReadingRules, provenance: Provenance
) -> Outcome[Statement]:
    reasons: list[Reason] = []

    if doc.currency is None:
        reasons.append(Reason(Code.CURRENCY_UNKNOWN))
    period: tuple[date, date] | None = None
    if doc.period is None:
        reasons.append(Reason(Code.PERIOD_MISSING))
    else:
        a = parse_date(doc.period[0], rules.period_format)
        b = parse_date(doc.period[1], rules.period_format)
        if isinstance(a, Ok) and isinstance(b, Ok):
            period = (a.value, b.value)
        else:
            reasons.extend(o.reasons[0] for o in (a, b) if isinstance(o, Fail))

    balances: dict[str, Decimal] = {}
    for what, raw, missing in (
        ("opening", doc.opening, Code.OPENING_MISSING),
        ("closing", doc.closing, Code.CLOSING_MISSING),
    ):
        if _blank(raw):
            reasons.append(Reason(missing))
            continue
        assert raw is not None
        p = _money(raw, rules, what, None)
        if isinstance(p, Fail):
            reasons.extend(p.reasons)
        else:
            balances[what] = _signed_balance(p.value)

    txns: list[Txn] = []
    for seq, row in enumerate(doc.rows):
        posted = parse_date(row.posted, rules.row_date_format, period)
        if isinstance(posted, Fail):
            reasons.append(
                Reason(
                    Code.UNPARSEABLE_DATE,
                    posted.reasons[0].detail,
                    seq=seq,
                    line_ids=row.line_ids,
                )
            )
            continue
        value_date: date | None = None
        if not _blank(row.value_date):
            assert row.value_date is not None
            vd = parse_date(row.value_date, rules.row_date_format, period)
            if isinstance(vd, Fail):
                reasons.append(
                    Reason(
                        Code.UNPARSEABLE_DATE,
                        vd.reasons[0].detail,
                        seq=seq,
                        line_ids=row.line_ids,
                    )
                )
                continue
            value_date = vd.value
        legs = _legs(row, rules, seq)
        if isinstance(legs, Fail):
            reasons.extend(
                Reason(r.code, r.detail, seq=seq, line_ids=row.line_ids)
                for r in legs.reasons
            )
            continue
        balance: Decimal | None = None
        if not _blank(row.balance):  # INV-10: "0.00" is not blank
            assert row.balance is not None
            bal = _money(row.balance, rules, "balance", seq)
            if isinstance(bal, Fail):
                reasons.extend(
                    Reason(r.code, r.detail, seq=seq, line_ids=row.line_ids)
                    for r in bal.reasons
                )
                continue
            balance = _signed_balance(bal.value)
        try:
            txns.append(
                Txn(
                    seq=seq,
                    posted=posted.value,
                    value_date=value_date,
                    description=norm_ws(row.description),
                    debit=legs.value[0],
                    credit=legs.value[1],
                    balance=balance,
                    reference=norm_ws(row.reference) if row.reference else None,
                    source=SourceSpan(page=row.page, line_ids=row.line_ids),
                )
            )
        except ValidationError as exc:
            reasons.append(
                Reason(
                    Code.ROW_INVALID_LEGS,
                    exc.errors()[0]["msg"],
                    seq=seq,
                    line_ids=row.line_ids,
                )
            )

    if reasons:
        return Fail(*reasons)
    assert period is not None and doc.currency is not None
    try:
        return Ok(
            Statement(
                doc_id=doc.doc_id,
                account=doc.account,
                currency=doc.currency,
                period_start=period[0],
                period_end=period[1],
                opening_balance=balances["opening"],
                closing_balance=balances["closing"],
                balance_policy=rules.balance_policy,
                transactions=tuple(txns),
                provenance=provenance,
            )
        )
    except ValidationError as exc:
        # Precision beyond the currency's minor unit, or an unsupported
        # currency: a misread, reported as one.
        return Fail(Reason(Code.UNPARSEABLE_MONEY, exc.errors()[0]["msg"]))
