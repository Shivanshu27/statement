"""INV-06: every value a model returns must be printed on the page.

This removes the "made-up but plausible" failure class entirely for
text-layer PDFs. A model may still put a real number in the wrong column —
the verifier catches most of that — but it cannot invent one.
"""

from __future__ import annotations

from dataclasses import dataclass

from statement.domain.money import MINOR_UNITS
from statement.domain.reasons import Code, Reason
from statement.domain.text import TextDocument, norm_ws
from statement.rescue.schema import LlmDoc, LlmRow

_SYMBOLS = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}


@dataclass(frozen=True, slots=True)
class Grounded:
    doc: LlmDoc  # ungrounded cells replaced by None
    reasons: tuple[Reason, ...]


def _norm(text: str) -> str:
    return norm_ws(text).casefold()


def _grounded_in(value: str, haystack: str) -> bool:
    return bool(value.strip()) and _norm(value) in haystack


def _currency_grounded(value: str, doc_text: str) -> bool:
    code = value.strip().upper()
    if code not in MINOR_UNITS:
        return False
    return code in doc_text or any(
        sym in doc_text for sym, c in _SYMBOLS.items() if c == code
    )


def ground(llm: LlmDoc, doc: TextDocument) -> Grounded:
    lines = doc.line_map()
    order = {lid: i for i, lid in enumerate(lines)}
    doc_text_raw = doc.full_text()
    doc_text = _norm(doc_text_raw)
    reasons: list[Reason] = []

    def check_doc_field(name: str, value: str | None) -> str | None:
        if value is None:
            return None
        if _grounded_in(value, doc_text):
            return value
        reasons.append(Reason(Code.RESCUE_UNGROUNDED, f"{name} {value!r} not on page"))
        return None

    currency = llm.currency
    if currency is not None and not _currency_grounded(currency, doc_text_raw):
        reasons.append(Reason(Code.RESCUE_UNGROUNDED, f"currency {currency!r}"))
        currency = None

    seen: set[str] = set()
    rows: list[LlmRow] = []
    for idx, row in enumerate(llm.rows):
        unknown = [lid for lid in row.line_ids if lid not in lines]
        if unknown:
            reasons.append(
                Reason(Code.RESCUE_UNKNOWN_LINE, f"row {idx}", line_ids=tuple(unknown))
            )
            continue
        dup = [lid for lid in row.line_ids if lid in seen]
        if dup:
            # The same printed line claimed by two rows: a duplicate or a merge.
            reasons.append(
                Reason(Code.RESCUE_DUPLICATE_LINE, f"row {idx}", line_ids=tuple(dup))
            )
        seen.update(row.line_ids)

        text = _norm(" ".join(lines[lid].text for lid in row.line_ids))
        first = lines[row.line_ids[0]]
        # Layouts that print a date only on a day's first row: the date may be
        # grounded on an earlier line of the same page, never on another page.
        page_so_far = _norm(
            " ".join(
                ln.text
                for ln in doc.pages[first.page].lines
                if order[ln.line_id] <= order[first.line_id]
            )
        )
        fixed: dict[str, str | None] = {}
        for name in ("date", "debit", "credit", "amount", "balance"):
            value = getattr(row, name)
            if value is None:
                continue
            haystack = page_so_far if name == "date" else text
            if not _grounded_in(value, haystack):
                reasons.append(
                    Reason(
                        Code.RESCUE_UNGROUNDED,
                        f"{name} {value!r}",
                        line_ids=row.line_ids,
                    )
                )
                fixed[name] = "" if name == "date" else None
        desc_tokens = _norm(row.description).split()
        text_tokens = set(text.split())
        if any(tok not in text_tokens for tok in desc_tokens):
            reasons.append(
                Reason(
                    Code.RESCUE_UNGROUNDED, "description altered", line_ids=row.line_ids
                )
            )
        rows.append(row.model_copy(update=fixed) if fixed else row)

    # Statement order is data: order rows by where they are printed, never by
    # the order the model happened to list them in.
    rows.sort(key=lambda r: order[r.line_ids[0]])

    grounded = LlmDoc(
        currency=currency,
        period_start=check_doc_field("period_start", llm.period_start),
        period_end=check_doc_field("period_end", llm.period_end),
        opening_balance=check_doc_field("opening_balance", llm.opening_balance),
        closing_balance=check_doc_field("closing_balance", llm.closing_balance),
        rows=tuple(rows),
    )
    return Grounded(grounded, tuple(reasons))
