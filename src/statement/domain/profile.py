"""Layout profiles: a layout's quirks as validated data (BUILD-PLAN §C5, ADR-0005).

A profile describes what each column *means* and how its cells are spelled.
Geometry is found at runtime from the header row, which is what makes Tier 1
tolerant of columns that drift.

The schema is deliberately narrow. It has no per-document fields and no place
for literal amounts, so an onboarding agent cannot memorise answers into a
profile (BUILD-PLAN §E3). Unknown keys are errors.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from statement.domain.assemble import AmountMode
from statement.domain.model import BalancePolicy
from statement.domain.parsing import NumberLocale


class Role(StrEnum):
    POSTED = "posted"
    VALUE_DATE = "value_date"
    DESCRIPTION = "description"
    REFERENCE = "reference"
    DEBIT = "debit"
    CREDIT = "credit"
    AMOUNT = "amount"
    BALANCE = "balance"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Align(StrEnum):
    LEFT = "left"
    RIGHT = "right"


_RIGHT_ROLES = frozenset({"debit", "credit", "amount", "balance"})


class Column(_Strict):
    role: Role
    header: str = Field(min_length=1)
    align: Align | None = None  # default: amounts right-aligned, text left

    @property
    def alignment(self) -> Align:
        if self.align is not None:
            return self.align
        return Align.RIGHT if self.role.value in _RIGHT_ROLES else Align.LEFT


class Fingerprint(_Strict):
    required_tokens: tuple[str, ...] = Field(min_length=1)


class Labelled(_Strict):
    """A value found on the line containing ``label``: the last amount after it."""

    label: str = Field(min_length=1)


class Period(_Strict):
    pattern: str  # regex with exactly two groups: start, end
    format: str

    @field_validator("pattern")
    @classmethod
    def _two_groups(cls, v: str) -> str:
        if re.compile(v).groups != 2:
            raise ValueError("period.pattern must have exactly two groups")
        return v


class Rows(_Strict):
    skip_patterns: tuple[str, ...] = ()  # regexes on the full line text
    stop_patterns: tuple[str, ...] = ()  # end of the table on this page
    date_carry_forward: bool = False  # date printed only on a day's first row

    @field_validator("skip_patterns", "stop_patterns")
    @classmethod
    def _compiles(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for p in v:
            re.compile(p)
        return v


class Profile(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    description: str = ""
    fingerprint: Fingerprint
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    columns: tuple[Column, ...] = Field(min_length=3)
    locale: NumberLocale
    date_format: str
    amount_mode: AmountMode
    balance_policy: BalancePolicy
    period: Period
    opening: Labelled
    closing: Labelled
    account: Labelled | None = None
    rows: Rows = Rows()
    tolerance_days: int = Field(default=0, ge=0, le=7)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        roles = [c.role for c in self.columns]
        if len(set(roles)) != len(roles):
            raise ValueError("a role may appear in at most one column")
        need = {Role.POSTED, Role.DESCRIPTION}
        if not need <= set(roles):
            raise ValueError("profile needs posted and description columns")
        has_split = Role.DEBIT in roles and Role.CREDIT in roles
        has_amount = Role.AMOUNT in roles
        if self.amount_mode is AmountMode.SPLIT and not has_split:
            raise ValueError("split amount_mode needs debit and credit columns")
        if self.amount_mode is not AmountMode.SPLIT and not has_amount:
            raise ValueError(f"{self.amount_mode} amount_mode needs an amount column")
        has_balance = Role.BALANCE in roles
        if (self.balance_policy is BalancePolicy.EVERY_ROW) != has_balance:
            raise ValueError("balance_policy must match presence of a balance column")
        return self

    def column(self, role: Role) -> Column | None:
        return next((c for c in self.columns if c.role is role), None)
