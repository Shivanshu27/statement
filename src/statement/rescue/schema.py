"""The shape Tier 2 accepts from a model. Anything else is RESCUE_UNPARSEABLE."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.reasons import Code, Reason


class _Loose(BaseModel):
    # Models add harmless extra keys; ignoring them is safe because nothing
    # here is trusted until grounded. Missing or mistyped keys still fail.
    model_config = ConfigDict(extra="ignore", frozen=True)


class LlmRow(_Loose):
    line_ids: tuple[str, ...] = Field(min_length=1)
    date: str
    description: str = ""
    debit: str | None = None
    credit: str | None = None
    amount: str | None = None
    balance: str | None = None


class LlmDoc(_Loose):
    currency: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None
    rows: tuple[LlmRow, ...]


_FENCE = re.compile(r"\{.*\}", re.DOTALL)


def parse_response(text: str) -> Outcome[LlmDoc]:
    m = _FENCE.search(text)
    if not m:
        return Fail(Reason(Code.RESCUE_UNPARSEABLE, "no JSON object in reply"))
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        # A reasoning model that spent its budget thinking returns truncated
        # JSON; that's a budget problem, reported as unparseable (G5).
        return Fail(Reason(Code.RESCUE_UNPARSEABLE, f"invalid JSON: {exc.msg}"))
    try:
        return Ok(LlmDoc.model_validate(data))
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return Fail(Reason(Code.RESCUE_UNPARSEABLE, f"{loc}: {first['msg']}"))
