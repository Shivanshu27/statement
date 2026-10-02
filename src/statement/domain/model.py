"""The canonical output contract (BUILD-PLAN §B1).

Everything that leaves the pipeline is one of these. Tier 1, Tier 2, and the
forge's ground truth all produce the same type, so the scorer compares like
with like.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from statement.domain.money import Money, quantise


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class BalancePolicy(StrEnum):
    """How a layout prints the running balance (decides whether INV-02 applies)."""

    EVERY_ROW = "every_row"
    NONE = "none"  # reduced trust: only INV-01 can verify amounts (ADR-0014)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSpan(_Frozen):
    page: int
    line_ids: tuple[str, ...]


class Txn(_Frozen):
    seq: int = Field(ge=0)
    posted: date
    value_date: date | None = None
    description: str
    debit: Money = Decimal(0)
    credit: Money = Decimal(0)
    balance: Money | None = None
    reference: str | None = None
    source: SourceSpan | None = None

    @model_validator(mode="after")
    def _single_signed_leg(self) -> Self:
        # INV-03: exactly one of debit/credit is non-zero; both non-negative.
        if self.debit < 0 or self.credit < 0:
            raise ValueError("debit and credit must be non-negative (INV-03)")
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("exactly one of debit/credit must be non-zero (INV-03)")
        return self

    @property
    def direction(self) -> Direction:
        return Direction.DEBIT if self.debit > 0 else Direction.CREDIT

    @property
    def amount(self) -> Decimal:
        return self.debit if self.debit > 0 else self.credit

    @property
    def signed(self) -> Decimal:
        return self.credit - self.debit


class Provenance(_Frozen):
    tier: Literal[0, 1, 2]  # 0 = ground truth from the forge
    profile_id: str | None = None
    profile_version: int | None = None
    model_id: str | None = None
    prompt_hash: str | None = None


class Statement(_Frozen):
    doc_id: str
    account: str | None = None  # masked; never the full number
    currency: str
    period_start: date
    period_end: date
    opening_balance: Money
    closing_balance: Money
    balance_policy: BalancePolicy
    transactions: tuple[Txn, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("period ends before it starts")
        # Quantisation doubles as a precision check: 12.345 INR is a misread.
        for value in (self.opening_balance, self.closing_balance):
            quantise(value, self.currency)
        for t in self.transactions:
            for v in (t.debit, t.credit, t.balance):
                if v is not None:
                    quantise(v, self.currency)
        if [t.seq for t in self.transactions] != list(range(len(self.transactions))):
            raise ValueError("transaction seq must be 0..n-1 in statement order")
        return self
