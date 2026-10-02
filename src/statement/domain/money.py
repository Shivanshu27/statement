"""Money is ``Decimal``, quantised to the currency's minor unit. Never float.

INV-09 lives here. ``float`` can enter Python from anywhere, so the check is
done at the boundary where a value becomes money, not by convention.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator

# ISO 4217 minor units for the currencies the forge and the profiles use.
# An unknown currency is an error, not a default: guessing the exponent of
# money is exactly the kind of silent assumption this project exists to avoid.
MINOR_UNITS: dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
}


class FloatMoneyError(ValueError):
    """A float reached a money path (INV-09).

    A ValueError so pydantic reports it as a validation failure of the field,
    with the field name, instead of crashing out of model construction.
    """


def quantum(currency: str) -> Decimal:
    try:
        exp = MINOR_UNITS[currency]
    except KeyError as exc:
        raise ValueError(f"unsupported currency {currency!r}") from exc
    return Decimal(1).scaleb(-exp)


def to_money(value: object) -> Decimal:
    """Coerce an int/str/Decimal to Decimal; refuse float outright."""
    if isinstance(value, bool):
        raise ValueError("bool is not money")
    if isinstance(value, float):
        raise FloatMoneyError(f"float {value!r} reached a money field (INV-09)")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal: {value!r}") from exc
    raise ValueError(f"cannot make money from {type(value).__name__}")


def quantise(value: Decimal, currency: str) -> Decimal:
    q = quantum(currency)
    out = value.quantize(q, rounding=ROUND_HALF_EVEN)
    if out != value:
        # A value with more precision than the currency allows was misread,
        # not "slightly off". Refuse rather than round it into plausibility.
        raise ValueError(f"{value} has more precision than {currency} allows")
    return out


Money = Annotated[Decimal, BeforeValidator(to_money)]
