"""Strict normalisation: exact value or refusal, never a guess (§G5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from statement.domain.outcome import Fail, Ok
from statement.domain.parsing import (
    Marker,
    NumberLocale,
    infer_date_format,
    infer_number_locale,
    parse_amount,
    parse_date,
)
from statement.domain.reasons import Code

DOT, COMMA = NumberLocale.DOT_DECIMAL, NumberLocale.COMMA_DECIMAL


@pytest.mark.parametrize(
    ("raw", "locale", "value", "marker"),
    [
        ("1,234.56", DOT, "1234.56", Marker.NONE),
        ("1,00,000.00", DOT, "100000.00", Marker.NONE),  # Indian lakh grouping
        ("12,34,56,789.00", DOT, "123456789.00", Marker.NONE),  # crore
        ("1.234,56", COMMA, "1234.56", Marker.NONE),
        ("-1,234.56", DOT, "1234.56", Marker.MINUS),
        ("−1,234.56", DOT, "1234.56", Marker.MINUS),  # Unicode minus
        ("1,234.56-", DOT, "1234.56", Marker.MINUS),  # trailing minus
        ("(1.234,56)", COMMA, "1234.56", Marker.MINUS),  # parentheses
        ("1,234.56 Dr", DOT, "1234.56", Marker.DR),
        ("1,234.56 CR", DOT, "1234.56", Marker.CR),
        ("$12,345.67", DOT, "12345.67", Marker.NONE),
        ("-$12.00", DOT, "12.00", Marker.MINUS),
        ("0.00", DOT, "0.00", Marker.NONE),
        ("+50.00", DOT, "50.00", Marker.PLUS),
    ],
)
def test_amount_spellings(
    raw: str, locale: NumberLocale, value: str, marker: Marker
) -> None:
    out = parse_amount(raw, locale)
    assert isinstance(out, Ok), out
    assert out.value.value == Decimal(value)
    assert out.value.marker is marker


@pytest.mark.parametrize(
    ("raw", "locale"),
    [
        ("1,2,3", DOT),  # not a grouping anyone uses
        ("12,3456.00", DOT),
        ("1,234.56", COMMA),  # wrong locale must refuse, not reinterpret
        ("(12.00) Dr", DOT),  # two sign markers
        ("--5.00", DOT),
        ("abc", DOT),
        ("", DOT),
        ("1.234.567", DOT),
    ],
)
def test_amount_refusals(raw: str, locale: NumberLocale) -> None:
    out = parse_amount(raw, locale)
    assert isinstance(out, Fail)
    assert out.reasons[0].code is Code.UNPARSEABLE_MONEY


def test_locale_inference_needs_evidence() -> None:
    assert infer_number_locale(["1,234.56", "12.00"]) is DOT
    assert infer_number_locale(["1.234,56", "(12,00)"]) is COMMA
    assert infer_number_locale(["1.234"]) is None  # 1.234 or 1234? undecidable
    assert infer_number_locale(["1,234.56", "1.234,56"]) is None  # contradictory


def test_yearless_dates_roll_over_new_year() -> None:
    period = (date(2025, 12, 15), date(2026, 1, 14))
    assert parse_date("28 Dec", "%d %b", period) == Ok(date(2025, 12, 28))
    assert parse_date("02 Jan", "%d %b", period) == Ok(date(2026, 1, 2))
    leap = (date(2024, 2, 1), date(2024, 3, 1))
    assert parse_date("29 Feb", "%d %b", leap) == Ok(date(2024, 2, 29))


def test_date_format_inferred_from_evidence() -> None:
    # 13/03 can only be DD/MM.
    out = infer_date_format(("01/03/2025", "31/03/2025"), ["02/03/2025", "13/03/2025"])
    assert out == Ok(("%d/%m/%Y", "%d/%m/%Y"))
    # US period ends on 03/31: only MM/DD fits.
    out = infer_date_format(("03/01/2025", "03/31/2025"), ["03/02/2025", "03/04/2025"])
    assert out == Ok(("%m/%d/%Y", "%m/%d/%Y"))


def test_ambiguous_date_format_is_reported_not_guessed() -> None:
    # Every day <= 12 and both readings fit inside a long period: refuse (F08).
    out = infer_date_format(("01/01/2025", "12/12/2025"), ["02/03/2025", "04/05/2025"])
    assert isinstance(out, Fail)
    assert out.reasons[0].code is Code.DATE_FORMAT_AMBIGUOUS
