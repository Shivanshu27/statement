"""H1: does balance-chain verification catch the errors extraction makes?

Take a correct statement, apply one failure from the catalogue (BUILD-PLAN
§B4), and ask the verifier. Two classes are *expected* to escape — F06
(description on the wrong row) and F13 (two errors that cancel) — and are
reported as escapes, not hidden. That gap is why L3 evaluation exists (§B5).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from statement.domain.model import BalancePolicy, Statement, Txn
from statement.domain.verify import verify

Mutation = Callable[[Statement, random.Random], Statement | None]


def _with(stmt: Statement, txns: list[Txn]) -> Statement:
    reseq = [t.model_copy(update={"seq": i}) for i, t in enumerate(txns)]
    return stmt.model_copy(update={"transactions": tuple(reseq)})


def _rebuild(stmt: Statement, txns: list[dict[str, object]]) -> Statement:
    """Re-validate: a mutation that breaks the model is caught by construction."""
    built = [Txn.model_validate({**t, "seq": i}) for i, t in enumerate(txns)]
    return Statement.model_validate({**stmt.model_dump(), "transactions": built})


def _pick(stmt: Statement, rng: random.Random, need: int = 1) -> int | None:
    n = len(stmt.transactions)
    return rng.randrange(n - need + 1) if n >= need else None


def f01_drop(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = list(s.transactions)
    del t[i]
    return _with(s, t)


def f02_duplicate(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = list(s.transactions)
    t.insert(i + 1, t[i])
    return _with(s, t)


def f03_swap_direction(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    t[i]["debit"], t[i]["credit"] = t[i]["credit"], t[i]["debit"]
    return _rebuild(s, t)


def f04_transpose_digits(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    leg = "debit" if t[i]["debit"] else "credit"
    digits = list(f"{t[i][leg]:.2f}".replace(".", ""))
    spots = [k for k in range(len(digits) - 1) if digits[k] != digits[k + 1]]
    if not spots:
        return None
    k = rng.choice(spots)
    digits[k], digits[k + 1] = digits[k + 1], digits[k]
    value = Decimal("".join(digits)).scaleb(-2)
    if value == 0:
        return None
    t[i][leg] = value
    return _rebuild(s, t)


def f05_merge(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng, 2)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    a, b = t[i], t[i + 1]
    a["description"] = f"{a['description']} {b['description']}"
    a["balance"] = b["balance"]
    del t[i + 1]
    return _rebuild(s, t)


def f06_swap_descriptions(s: Statement, rng: random.Random) -> Statement | None:
    t = [x.model_dump() for x in s.transactions]
    idx = [
        k for k in range(len(t) - 1) if t[k]["description"] != t[k + 1]["description"]
    ]
    if not idx:
        return None
    k = rng.choice(idx)
    t[k]["description"], t[k + 1]["description"] = (
        t[k + 1]["description"],
        t[k]["description"],
    )
    return _rebuild(s, t)


def _shift_year(d: date) -> date:
    return d.replace(year=d.year + 1, day=min(d.day, 28))


def f07_wrong_year(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    t[i]["posted"] = _shift_year(t[i]["posted"])
    return _rebuild(s, t)


def f08_day_month_swap(s: Statement, rng: random.Random) -> Statement | None:
    t = [x.model_dump() for x in s.transactions]
    idx = [
        k
        for k, x in enumerate(t)
        if x["posted"].day <= 12 and x["posted"].day != x["posted"].month
    ]
    if not idx:
        return None
    k = rng.choice(idx)
    d: date = t[k]["posted"]
    t[k]["posted"] = date(d.year, d.day, d.month)
    return _rebuild(s, t)


def f09_locale_misread(s: Statement, rng: random.Random) -> Statement | None:
    i = _pick(s, rng)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    leg = "debit" if t[i]["debit"] else "credit"
    t[i][leg] = t[i][leg] * 100  # decimal mark lost
    return _rebuild(s, t)


def f10_summary_as_txn(s: Statement, rng: random.Random) -> Statement | None:
    t = [x.model_dump() for x in s.transactions]
    t.insert(
        0,
        {
            "seq": 0,
            "posted": s.period_start,
            "description": "Balance brought forward",
            "debit": Decimal(0),
            "credit": s.opening_balance if s.opening_balance > 0 else Decimal(1),
            "balance": s.opening_balance
            if s.balance_policy is BalancePolicy.EVERY_ROW
            else None,
        },
    )
    return _rebuild(s, t)


def f12_zero_as_missing(s: Statement, rng: random.Random) -> Statement | None:
    if s.balance_policy is not BalancePolicy.EVERY_ROW:
        return None
    i = _pick(s, rng)
    if i is None:
        return None
    t = [x.model_dump() for x in s.transactions]
    t[i]["balance"] = None
    return _rebuild(s, t)


def f13_compensating(s: Statement, rng: random.Random) -> Statement | None:
    """Two errors that cancel: row i off by +d, row i+1 off by -d, balances adjusted."""
    t = [x.model_dump() for x in s.transactions]
    cands = [
        k
        for k in range(len(t) - 1)
        if t[k]["debit"] and t[k + 1]["debit"] and t[k + 1]["debit"] > Decimal(1)
    ]
    if not cands:
        return None
    k = rng.choice(cands)
    d = Decimal(1)
    t[k]["debit"] = t[k]["debit"] + d
    if t[k]["balance"] is not None:
        t[k]["balance"] = t[k]["balance"] - d
    t[k + 1]["debit"] = t[k + 1]["debit"] - d
    return _rebuild(s, t)


MUTATIONS: dict[str, tuple[Mutation, bool]] = {
    # code: (mutation, expected to be detectable by L2)
    "F01_row_dropped": (f01_drop, True),
    "F02_row_duplicated": (f02_duplicate, True),
    "F03_direction_swapped": (f03_swap_direction, True),
    "F04_digits_transposed": (f04_transpose_digits, True),
    "F05_rows_merged": (f05_merge, True),
    "F06_description_misattached": (f06_swap_descriptions, False),
    "F07_wrong_year": (f07_wrong_year, True),
    "F08_day_month_swapped": (f08_day_month_swap, True),
    "F09_locale_misread": (f09_locale_misread, True),
    "F10_summary_read_as_txn": (f10_summary_as_txn, True),
    "F12_zero_read_as_missing": (f12_zero_as_missing, True),
    "F13_compensating_errors": (f13_compensating, False),
}


@dataclass
class Tally:
    applied: int = 0
    detected: int = 0
    by_construction: int = 0  # the model itself refused the corrupted value

    @property
    def rate(self) -> float:
        return self.detected / self.applied if self.applied else 0.0


def run(truths: list[Statement], *, seed: int = 0, trials: int = 3) -> dict[str, Tally]:
    out = {code: Tally() for code in MUTATIONS}
    for n, stmt in enumerate(truths):
        for code, (mutate, _) in MUTATIONS.items():
            for trial in range(trials):
                rng = random.Random(f"corrupt:{seed}:{n}:{code}:{trial}")
                tally = out[code]
                try:
                    bad = mutate(stmt, rng)
                except ValidationError:
                    tally.applied += 1
                    tally.detected += 1
                    tally.by_construction += 1
                    continue
                if bad is None or bad == stmt:
                    continue
                tally.applied += 1
                if not verify(bad, tolerance_days=0).ok:
                    tally.detected += 1
    return out
