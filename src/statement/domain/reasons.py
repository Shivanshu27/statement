"""Machine-readable reasons a document is not ``ACCEPTED``.

The pipeline branches on these, the scorecard groups by them, and
``statement explain`` prints them. They are values, not exceptions (§C8).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Code(StrEnum):
    # ① ingest / ② text layer -> REJECTED
    NOT_PDF = "NOT_PDF"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    TOO_LARGE = "TOO_LARGE"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"

    # ③ classify / ④ tier 1 extraction
    UNKNOWN_LAYOUT = "UNKNOWN_LAYOUT"
    AMBIGUOUS_LAYOUT = "AMBIGUOUS_LAYOUT"
    HEADER_NOT_FOUND = "HEADER_NOT_FOUND"
    PERIOD_MISSING = "PERIOD_MISSING"
    OPENING_MISSING = "OPENING_MISSING"
    CLOSING_MISSING = "CLOSING_MISSING"
    CURRENCY_UNKNOWN = "CURRENCY_UNKNOWN"
    UNPARSEABLE_MONEY = "UNPARSEABLE_MONEY"
    UNPARSEABLE_DATE = "UNPARSEABLE_DATE"
    DATE_FORMAT_AMBIGUOUS = "DATE_FORMAT_AMBIGUOUS"
    ROW_INVALID_LEGS = "ROW_INVALID_LEGS"
    ROW_UNPARSED = "ROW_UNPARSED"
    NO_ROWS = "NO_ROWS"

    # ⑤ / ⑦ verification
    TOTALS_MISMATCH = "TOTALS_MISMATCH"
    CHAIN_BREAK = "CHAIN_BREAK"
    BALANCE_MISSING = "BALANCE_MISSING"
    DATE_ORDER = "DATE_ORDER"
    DATE_OUT_OF_PERIOD = "DATE_OUT_OF_PERIOD"

    # ⑥ tier 2 rescue
    RESCUE_UNAVAILABLE = "RESCUE_UNAVAILABLE"
    RESCUE_UNPARSEABLE = "RESCUE_UNPARSEABLE"
    RESCUE_UNGROUNDED = "RESCUE_UNGROUNDED"
    RESCUE_UNKNOWN_LINE = "RESCUE_UNKNOWN_LINE"
    RESCUE_DUPLICATE_LINE = "RESCUE_DUPLICATE_LINE"
    RESCUE_BUDGET = "RESCUE_BUDGET"
    RESCUE_CACHE_MISS = "RESCUE_CACHE_MISS"
    RESCUE_ERROR = "RESCUE_ERROR"


# Codes that mean "this is not a document we can work with at all".
REJECTING: frozenset[Code] = frozenset(
    {
        Code.NOT_PDF,
        Code.PDF_ENCRYPTED,
        Code.TOO_LARGE,
        Code.TOO_MANY_PAGES,
        Code.NO_TEXT_LAYER,
    }
)


@dataclass(frozen=True, slots=True)
class Reason:
    code: Code
    detail: str = ""
    seq: int | None = None  # transaction index, when the reason is row-level
    line_ids: tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f" @seq {self.seq}" if self.seq is not None else ""
        lines = f" [{', '.join(self.line_ids)}]" if self.line_ids else ""
        detail = f": {self.detail}" if self.detail else ""
        return f"{self.code}{where}{lines}{detail}"
