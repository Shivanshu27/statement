"""Tier 1: classify the layout and extract by profile, deterministically.

Columns are found from the header row on each page, then words are assigned
to columns by position. No LLM, no network, milliseconds per document.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from statement.domain.assemble import RawDoc, RawRow, ReadingRules, assemble
from statement.domain.model import Provenance
from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.parsing import looks_like_amount, parse_date
from statement.domain.profile import Align, Labelled, Profile, Role
from statement.domain.reasons import Code, Reason
from statement.domain.text import Line, TextDocument, Word
from statement.ports import Extraction

# ------------------------------------------------------------------ geometry


# How far left of its header a right-aligned value may start. Real values
# are usually wider than short headers like "Amount".
_MIN_REACH = 40.0


@dataclass(frozen=True, slots=True)
class Region:
    role: Role
    lo: float
    hi: float


def _match_header(
    words: Sequence[Word], header: str, start: int
) -> tuple[int, int] | None:
    tokens = header.split()
    for i in range(start, len(words) - len(tokens) + 1):
        if all(words[i + k].text == tokens[k] for k in range(len(tokens))):
            return i, i + len(tokens) - 1
    return None


def locate_header(line: Line, profile: Profile) -> tuple[Region, ...] | None:
    """Find every column header, left to right, on one line; None if any is missing."""
    words = line.words
    spans: list[tuple[Role, Align, float, float]] = []
    cursor = 0
    for col in profile.columns:
        hit = _match_header(words, col.header, cursor)
        if hit is None:
            return None
        first, last = hit
        spans.append((col.role, col.alignment, words[first].x0, words[last].x1))
        cursor = last + 1
    # Boundaries come from alignment, not header midpoints: a wide
    # left-aligned narration runs far past its header, and right-aligned
    # amounts run left of theirs.
    bounds: list[float] = []
    for (_, _, _, cur_x1), (_, nxt_align, nxt_x0, nxt_x1) in pairwise(spans):
        if nxt_align is Align.LEFT:
            bounds.append(nxt_x0 - 2.0)
        else:
            reach = max(nxt_x1 - nxt_x0, _MIN_REACH)
            bounds.append(max(cur_x1 + 1.0, nxt_x0 - reach))
    edges = [float("-inf"), *bounds, float("inf")]
    return tuple(
        Region(role, edges[i], edges[i + 1]) for i, (role, *_rest) in enumerate(spans)
    )


def _cells(line: Line, regions: Sequence[Region]) -> dict[Role, str]:
    buckets: dict[Role, list[str]] = {r.role: [] for r in regions}
    for w in line.words:
        for r in regions:
            if r.lo <= w.center < r.hi:
                buckets[r.role].append(w.text)
                break
    return {role: " ".join(ws) for role, ws in buckets.items() if ws}


# ------------------------------------------------------------------ classify


def classify(doc: TextDocument, profiles: Sequence[Profile]) -> Outcome[Profile]:
    text = doc.full_text()
    first_lines = doc.pages[0].lines if doc.pages else ()
    matches = [
        p
        for p in profiles
        if all(tok in text for tok in p.fingerprint.required_tokens)
        and any(locate_header(line, p) for line in first_lines)
    ]
    if not matches:
        return Fail(Reason(Code.UNKNOWN_LAYOUT))
    matches.sort(key=lambda p: len(p.fingerprint.required_tokens), reverse=True)
    if len(matches) > 1 and len(matches[0].fingerprint.required_tokens) == len(
        matches[1].fingerprint.required_tokens
    ):
        ids = ", ".join(p.id for p in matches)
        return Fail(Reason(Code.AMBIGUOUS_LAYOUT, ids))
    return Ok(matches[0])


# ------------------------------------------------------------------ fields


def find_labelled(doc: TextDocument, spec: Labelled, profile: Profile) -> str | None:
    """The amount at the end of the first line containing ``spec.label``."""
    for line in doc.lines():
        text = line.text
        idx = text.find(spec.label)
        if idx < 0:
            continue
        tail = text[idx + len(spec.label) :].split()
        for n in (2, 1):  # "12,000.00 Cr" is two words
            if len(tail) >= n:
                candidate = " ".join(tail[-n:])
                if looks_like_amount(candidate, profile.locale):
                    return candidate
        return None
    return None


def find_account(doc: TextDocument, spec: Labelled) -> str | None:
    for line in doc.lines():
        idx = line.text.find(spec.label)
        if idx >= 0:
            digits = re.sub(r"\D", "", line.text[idx + len(spec.label) :])
            return f"XXXX{digits[-4:]}" if len(digits) >= 4 else None
    return None


def find_period(doc: TextDocument, profile: Profile) -> tuple[str, str] | None:
    pattern = re.compile(profile.period.pattern)
    for line in doc.lines():
        m = pattern.search(line.text)
        if m:
            return m.group(1), m.group(2)
    return None


# ------------------------------------------------------------------ rows


_AMOUNT_ROLES = (Role.DEBIT, Role.CREDIT, Role.AMOUNT, Role.BALANCE)


@dataclass
class _Building:
    line_ids: list[str]
    page: int
    cells: dict[Role, str]


def _rows(
    doc: TextDocument, profile: Profile, period_raw: tuple[str, str] | None
) -> tuple[list[RawRow], list[Reason]]:
    skip = [re.compile(p) for p in profile.rows.skip_patterns]
    stop = [re.compile(p) for p in profile.rows.stop_patterns]
    period = None
    if period_raw:
        a = parse_date(period_raw[0], profile.period.format)
        b = parse_date(period_raw[1], profile.period.format)
        if isinstance(a, Ok) and isinstance(b, Ok):
            period = (a.value, b.value)

    built: list[_Building] = []
    reasons: list[Reason] = []
    regions: tuple[Region, ...] | None = None

    for page in doc.pages:
        header_idx = next(
            (i for i, line in enumerate(page.lines) if locate_header(line, profile)),
            None,
        )
        if header_idx is not None:
            regions = locate_header(page.lines[header_idx], profile)
            body = page.lines[header_idx + 1 :]
            seen_row = True  # lines right under a header belong to the table
        elif regions is not None:
            body = page.lines  # header not repeated: reuse the last geometry
            seen_row = False
        else:
            continue
        assert regions is not None

        for line in body:
            text = line.text
            if any(p.search(text) for p in stop):
                break
            if any(p.search(text) for p in skip):
                continue
            cells = _cells(line, regions)
            posted = cells.get(Role.POSTED, "")
            has_amount = any(cells.get(r) for r in _AMOUNT_ROLES)
            if posted:
                if isinstance(parse_date(posted, profile.date_format, period), Fail):
                    if seen_row:
                        reasons.append(
                            Reason(
                                Code.ROW_UNPARSED,
                                f"date cell {posted!r}",
                                line_ids=(line.line_id,),
                            )
                        )
                    continue
                built.append(_Building([line.line_id], page.index, dict(cells)))
                seen_row = True
            elif has_amount:
                if profile.rows.date_carry_forward and built:
                    cells[Role.POSTED] = built[-1].cells[Role.POSTED]
                    built.append(_Building([line.line_id], page.index, dict(cells)))
                elif seen_row:
                    # Amounts with no date and no rule for them: never drop silently.
                    reasons.append(
                        Reason(Code.ROW_UNPARSED, text, line_ids=(line.line_id,))
                    )
            elif built and seen_row and cells.get(Role.DESCRIPTION):
                prev = built[-1]
                prev.line_ids.append(line.line_id)
                prev.cells[Role.DESCRIPTION] = (
                    prev.cells.get(Role.DESCRIPTION, "") + " " + cells[Role.DESCRIPTION]
                )

    rows = [
        RawRow(
            line_ids=tuple(b.line_ids),
            page=b.page,
            posted=b.cells[Role.POSTED],
            description=b.cells.get(Role.DESCRIPTION, ""),
            debit=b.cells.get(Role.DEBIT),
            credit=b.cells.get(Role.CREDIT),
            amount=b.cells.get(Role.AMOUNT),
            balance=b.cells.get(Role.BALANCE),
            value_date=b.cells.get(Role.VALUE_DATE),
            reference=b.cells.get(Role.REFERENCE),
        )
        for b in built
    ]
    return rows, reasons


def rules_for(profile: Profile) -> ReadingRules:
    return ReadingRules(
        locale=profile.locale,
        period_format=profile.period.format,
        row_date_format=profile.date_format,
        amount_mode=profile.amount_mode,
        balance_policy=profile.balance_policy,
    )


def extract(doc: TextDocument, profile: Profile) -> Extraction:
    if not any(locate_header(line, profile) for line in doc.lines()):
        return Extraction(None, (Reason(Code.HEADER_NOT_FOUND, profile.id),))
    period = find_period(doc, profile)
    rows, row_reasons = _rows(doc, profile, period)
    raw = RawDoc(
        doc_id=doc.doc_id,
        currency=profile.currency,
        account=find_account(doc, profile.account) if profile.account else None,
        period=period,
        opening=find_labelled(doc, profile.opening, profile),
        closing=find_labelled(doc, profile.closing, profile),
        rows=tuple(rows),
    )
    provenance = Provenance(
        tier=1, profile_id=profile.id, profile_version=profile.version
    )
    out = assemble(raw, rules_for(profile), provenance)
    if isinstance(out, Fail):
        return Extraction(None, tuple(row_reasons) + out.reasons)
    return Extraction(out.value, tuple(row_reasons))
