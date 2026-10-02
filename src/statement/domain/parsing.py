"""Normalising printed numbers and dates — strictly.

Every function here either returns an exact value or refuses. A parser that
"does its best" with ``1,2,3`` or a date that only half-matches is how a
plausible wrong number gets made, so ambiguity is an error, not a guess.

Traps handled deliberately (BUILD-PLAN §G5):
- Indian digit grouping ``1,00,000.00`` and EU ``1.000,00``.
- Five spellings of a sign: ``-``, ``−`` (U+2212), trailing ``-``,
  parentheses, and ``Dr``/``Cr`` suffixes.
- Year-less dates across New Year, resolved from the statement period.
- Printed ``0.00`` is the value zero, never "absent" (INV-10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.reasons import Code, Reason


class Marker(StrEnum):
    """The sign information a printed amount carried, before interpretation."""

    NONE = "none"
    MINUS = "minus"
    PLUS = "plus"
    DR = "dr"
    CR = "cr"


@dataclass(frozen=True, slots=True)
class PrintedAmount:
    value: Decimal  # always >= 0; the sign lives in ``marker``
    marker: Marker


class NumberLocale(StrEnum):
    DOT_DECIMAL = "dot"  # 1,234.56 and 1,23,456.78
    COMMA_DECIMAL = "comma"  # 1.234,56


_CURRENCY_TOKENS = ("₹", "$", "€", "£", "Rs.", "Rs", "INR", "USD", "EUR", "GBP")

# Integer part: plain digits, western thousands, or Indian lakh grouping.
_INT_DOT = r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)"
_INT_COMMA = r"(?:\d{1,3}(?:\.\d{3})+|\d+)"
_NUM_DOT = re.compile(rf"^(?P<int>{_INT_DOT})(?:\.(?P<frac>\d+))?$")
_NUM_COMMA = re.compile(rf"^(?P<int>{_INT_COMMA})(?:,(?P<frac>\d+))?$")
_SUFFIX = re.compile(r"^(?P<body>.*?)\s*(?P<sfx>dr|cr)\.?$", re.IGNORECASE)


def _strip_currency(text: str) -> str:
    out = text.strip()
    for token in _CURRENCY_TOKENS:
        if out.startswith(token):
            out = out[len(token) :].strip()
        if out.endswith(token):
            out = out[: -len(token)].strip()
    return out


def parse_amount(raw: str, locale: NumberLocale) -> Outcome[PrintedAmount]:
    text = raw.strip().replace("−", "-").replace(" ", " ")
    if not text:
        return Fail(Reason(Code.UNPARSEABLE_MONEY, "empty"))
    marker = Marker.NONE

    m = _SUFFIX.match(text)
    if m:
        marker = Marker.DR if m.group("sfx").lower() == "dr" else Marker.CR
        text = m.group("body").strip()
    if text.startswith("(") and text.endswith(")"):
        if marker is not Marker.NONE:
            return Fail(Reason(Code.UNPARSEABLE_MONEY, f"two sign markers in {raw!r}"))
        marker, text = Marker.MINUS, text[1:-1].strip()
    # Currency may sit outside or inside the sign: "-$12.00", "$-12.00".
    text = _strip_currency(text)
    for prefix, mk in (("-", Marker.MINUS), ("+", Marker.PLUS)):
        if text.startswith(prefix):
            if marker is not Marker.NONE:
                return Fail(
                    Reason(Code.UNPARSEABLE_MONEY, f"two sign markers in {raw!r}")
                )
            marker, text = mk, text[1:].strip()
    if text.endswith("-"):
        if marker is not Marker.NONE:
            return Fail(Reason(Code.UNPARSEABLE_MONEY, f"two sign markers in {raw!r}"))
        marker, text = Marker.MINUS, text[:-1].strip()
    text = _strip_currency(text)

    pattern = _NUM_DOT if locale is NumberLocale.DOT_DECIMAL else _NUM_COMMA
    nm = pattern.match(text)
    if not nm:
        return Fail(Reason(Code.UNPARSEABLE_MONEY, f"{raw!r} ({locale})"))
    sep = "," if locale is NumberLocale.DOT_DECIMAL else "."
    integer = nm.group("int").replace(sep, "")
    frac = nm.group("frac") or ""
    value = Decimal(f"{integer}.{frac}") if frac else Decimal(integer)
    return Ok(PrintedAmount(value=value, marker=marker))


def looks_like_amount(raw: str, locale: NumberLocale) -> bool:
    return isinstance(parse_amount(raw, locale), Ok)


def infer_number_locale(raws: list[str]) -> NumberLocale | None:
    """Pick the locale under which every raw amount parses unambiguously.

    ``1.234`` is valid in both (1.234 vs 1234), so it never decides; a value
    with exactly two trailing digits after the last separator does.
    """
    votes: set[NumberLocale] = set()
    for raw in raws:
        body = raw.strip().rstrip("-").rstrip(")").strip()
        body = re.sub(r"\s*(dr|cr)\.?$", "", body, flags=re.IGNORECASE)
        if re.search(r"\.\d{2}$", body):
            votes.add(NumberLocale.DOT_DECIMAL)
        elif re.search(r",\d{2}$", body):
            votes.add(NumberLocale.COMMA_DECIMAL)
    if len(votes) != 1:
        return None
    (locale,) = votes
    if all(looks_like_amount(r, locale) for r in raws):
        return locale
    return None


# ------------------------------------------------------------------ dates

_HAS_YEAR = ("%Y", "%y")


def _has_year(fmt: str) -> bool:
    return any(tok in fmt for tok in _HAS_YEAR)


def parse_date(
    raw: str, fmt: str, period: tuple[date, date] | None = None
) -> Outcome[date]:
    """Parse ``raw`` with ``fmt``; year-less formats take the year from ``period``.

    Rows printing only ``28 Dec`` / ``02 Jan`` on a Dec–Jan statement belong
    to two different years. Appending the year ourselves (rather than letting
    strptime default to 1900) also keeps 29 Feb parseable.
    """
    text = " ".join(raw.split())
    if _has_year(fmt):
        try:
            return Ok(datetime.strptime(text, fmt).date())  # noqa: DTZ007 - a date, not a datetime
        except ValueError:
            return Fail(Reason(Code.UNPARSEABLE_DATE, f"{raw!r} vs {fmt!r}"))
    if period is None:
        return Fail(Reason(Code.UNPARSEABLE_DATE, f"{raw!r}: year-less, no period"))
    start, end = period
    for year in range(start.year, end.year + 1):
        try:
            d = datetime.strptime(f"{text} {year}", f"{fmt} %Y").date()  # noqa: DTZ007
        except ValueError:
            continue
        if start <= d <= end:
            return Ok(d)
    # Not inside the period under any year: report the start year's reading
    # so INV-04 names the real problem instead of hiding it here.
    try:
        return Ok(datetime.strptime(f"{text} {start.year}", f"{fmt} %Y").date())  # noqa: DTZ007
    except ValueError:
        return Fail(Reason(Code.UNPARSEABLE_DATE, f"{raw!r} vs {fmt!r}"))


# Formats Tier 2 may infer from. Order matters only for error messages: a
# format is chosen only if it is the *unique* one that fits all dates.
CANDIDATE_DATE_FORMATS: tuple[str, ...] = (
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d/%m/%y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%d %b %Y",
    "%d %b %y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d, %Y",
    "%d %b",
    "%d-%b",
)


def infer_date_format(
    period_raws: tuple[str, str], row_raws: list[str]
) -> Outcome[tuple[str, str]]:
    """Find the unique (period_fmt, row_fmt) pair that explains every date.

    DD/MM vs MM/DD is resolved by evidence, never by a default: a format is
    kept only if all dates parse, rows fall inside the period, and rows are
    non-decreasing. If two formats survive, the document is ambiguous and
    that is reported, not guessed (F08).
    """
    period_fmts: list[tuple[str, tuple[date, date]]] = []
    for fmt in CANDIDATE_DATE_FORMATS:
        if not _has_year(fmt):
            continue
        a, b = parse_date(period_raws[0], fmt), parse_date(period_raws[1], fmt)
        if isinstance(a, Ok) and isinstance(b, Ok) and a.value <= b.value:
            period_fmts.append((fmt, (a.value, b.value)))

    survivors: list[tuple[str, str]] = []
    for pfmt, period in period_fmts:
        for rfmt in CANDIDATE_DATE_FORMATS:
            parsed: list[date] = []
            for raw in row_raws:
                r = parse_date(raw, rfmt, period)
                if isinstance(r, Fail):
                    break
                parsed.append(r.value)
            else:
                inside = all(period[0] <= d <= period[1] for d in parsed)
                ordered = all(x <= y for x, y in pairwise(parsed))
                if inside and ordered:
                    survivors.append((pfmt, rfmt))
    if not survivors:
        return Fail(Reason(Code.UNPARSEABLE_DATE, "no date format fits the document"))
    if len(survivors) > 1:
        # Equivalent readings (e.g. same dates under two formats) are not
        # ambiguity; different readings are.
        readings = {
            tuple(
                _value(parse_date(raw, rf, _period(pf, period_raws)))
                for raw in row_raws
            )
            for pf, rf in survivors
        }
        if len(readings) > 1:
            fmts = ", ".join(sorted({rf for _, rf in survivors}))
            return Fail(Reason(Code.DATE_FORMAT_AMBIGUOUS, fmts))
    return Ok(survivors[0])


def _period(fmt: str, raws: tuple[str, str]) -> tuple[date, date] | None:
    a, b = parse_date(raws[0], fmt), parse_date(raws[1], fmt)
    if isinstance(a, Ok) and isinstance(b, Ok):
        return (a.value, b.value)
    return None


def _value(out: Outcome[date]) -> date | None:
    return out.value if isinstance(out, Ok) else None
