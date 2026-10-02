"""Six structurally distinct statement layouts.

Each one imitates a *structural* pattern seen in real statements — split
debit/credit columns, one signed column, Dr/Cr suffixes, parentheses for
negatives, brought/carried-forward rows, no running balance — under a
fictional bank name, with no real bank's branding (ADR-0011).

The layouts know the ground truth; the profiles in ``profiles/`` only know
what can be read off the page. Keeping the two independent is what makes
the round-trip test meaningful.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from statement.domain.model import BalancePolicy, Statement, Txn
from statement.forge.plan import Align, PagePlan, RenderPlan, TextItem, text_width, wrap

# ------------------------------------------------------------------ numbers


def _group(int_part: str, indian: bool) -> str:
    if len(int_part) <= 3:
        return int_part
    if not indian:
        out = []
        while int_part:
            out.append(int_part[-3:])
            int_part = int_part[:-3]
        return ",".join(reversed(out))
    head, tail = int_part[:-3], int_part[-3:]
    groups = []
    while head:
        groups.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(groups)) + "," + tail


def fmt_dot(value: Decimal, *, indian: bool = False) -> str:
    whole, frac = f"{abs(value):.2f}".split(".")
    return f"{_group(whole, indian)}.{frac}"


def fmt_eu(value: Decimal) -> str:
    whole, frac = f"{abs(value):.2f}".split(".")
    return f"{_group(whole, False).replace(',', '.')},{frac}"


# ------------------------------------------------------------------ engine

Row = dict[
    str, str
]  # column key -> cell text; "_text" = free text at the details column


@dataclass(frozen=True, slots=True)
class Col:
    key: str
    header: str
    x: float
    align: Align = Align.LEFT


@dataclass(frozen=True, slots=True)
class Layout:
    id: str
    bank: str
    currency: str
    cols: tuple[Col, ...]
    fmt_date: Callable[[date], str]
    fmt_period_date: Callable[[date], str]
    header_lines: Callable[[Statement, str, Layout], list[str]]
    cells: Callable[[Txn, Layout], Row]
    fmt_balance: Callable[[Decimal], str]
    balance_policy: BalancePolicy = BalancePolicy.EVERY_ROW
    with_reference: bool = False
    date_carry_forward: bool = False
    top_summary: Callable[[Statement, Layout], list[str]] | None = None
    pre_table: Callable[[Statement, Layout], list[Row]] | None = None
    end_rows: Callable[[Statement, Layout], list[Row]] | None = None
    page_close: Callable[[list[Txn], Decimal, bool, Layout], list[Row]] | None = None
    page_open: Callable[[Decimal, Layout], list[Row]] | None = None
    extras: dict[str, str] = field(default_factory=dict)

    def col(self, key: str) -> Col:
        return next(c for c in self.cols if c.key == key)

    def desc_width(self) -> float:
        keys = [c.key for c in self.cols]
        i = keys.index("description")
        nxt = self.cols[i + 1]
        if nxt.align is Align.LEFT:
            right = nxt.x
        else:
            # Must end left of where Tier 1 starts the next column: its header
            # start minus the reach allowed for wide right-aligned values.
            head = text_width(nxt.header, bold=True)
            right = nxt.x - head - max(head, 40.0)
        return right - self.col("description").x - 12


_LH = 11.5  # row height
_BODY_TOP_P1 = 175.0
_BODY_TOP_PN = 62.0
_FOOTER = 818.0


@dataclass
class _Page:
    rows: list[Row] = field(default_factory=list)
    txns: list[Txn] = field(default_factory=list)


def render(stmt: Statement, layout: Layout, seed: int) -> RenderPlan:
    rng = random.Random(f"render:{layout.id}:{seed}")
    jitter = {c.key: rng.uniform(-2.0, 2.0) for c in layout.cols}
    bottom = rng.choice((560.0, 680.0, 790.0))  # vary rows per page -> multi-page docs
    repeat_header = rng.random() > 0.2
    notice_p = 0.04 if rng.random() < 0.4 else 0.0
    account_full = f"{rng.randint(10_000_000, 99_999_999)}{stmt.account[-4:] if stmt.account else '0000'}"
    desc_w = layout.desc_width()

    pages: list[_Page] = [_Page()]
    capacity = int((bottom - _BODY_TOP_P1 - _LH) / _LH)
    used = 0
    reserve = 2 if layout.page_close else 0

    def push(rows: list[Row]) -> None:
        nonlocal used
        pages[-1].rows.extend(rows)
        used += len(rows)

    if layout.pre_table:
        push(layout.pre_table(stmt, layout))

    balance = stmt.opening_balance
    last_date_on_page: date | None = None
    for t in stmt.transactions:
        cells = layout.cells(t, layout)
        if layout.date_carry_forward and last_date_on_page == t.posted:
            cells["posted"] = ""
        desc_lines = wrap(t.description, desc_w)
        too_wide = [d for d in desc_lines if text_width(d) > desc_w]
        if too_wide:
            # A forge geometry bug, not a test case: overlapping text makes
            # pdfplumber interleave characters across columns. Refuse.
            raise ValueError(f"{layout.id}: {too_wide[0]!r} overflows {desc_w:.0f}pt")
        block: list[Row] = [{**cells, "description": desc_lines[0]}]
        block += [{"description": d} for d in desc_lines[1:]]
        if used + len(block) + reserve > capacity:
            if layout.page_close:
                push(layout.page_close(pages[-1].txns, balance, False, layout))
            pages.append(_Page())
            capacity = int((bottom - _BODY_TOP_PN - _LH) / _LH)
            used = 0
            last_date_on_page = None
            if layout.page_open:
                push(layout.page_open(balance, layout))
            if layout.date_carry_forward:
                block[0]["posted"] = layout.fmt_date(t.posted)
        push(block)
        pages[-1].txns.append(t)
        last_date_on_page = t.posted
        balance = balance + t.credit - t.debit
        if notice_p and rng.random() < notice_p:
            push(
                [
                    {
                        "_text": "*** Important: keep your contact details up to date with us ***"
                    }
                ]
            )

    if layout.page_close:
        push(layout.page_close(pages[-1].txns, balance, True, layout))
    if layout.end_rows:
        push(layout.end_rows(stmt, layout))

    out: list[PagePlan] = []
    n = len(pages)
    for p_idx, page in enumerate(pages):
        items: list[TextItem] = []
        if p_idx == 0:
            top = 40.0
            items.append(TextItem(36, top, layout.bank, size=12, bold=True))
            top += 18
            for text in layout.header_lines(stmt, account_full, layout):
                items.append(TextItem(36, top, text, size=8.5))
                top += 12
            if layout.top_summary:
                top += 4
                for text in layout.top_summary(stmt, layout):
                    items.append(TextItem(36, top, text, size=8.5))
                    top += 12
            body_top = max(top + 8, _BODY_TOP_P1 - _LH)
        else:
            items.append(
                TextItem(36, 40, f"{layout.bank} - statement continued", size=8)
            )
            body_top = _BODY_TOP_PN - _LH
        y = body_top
        if p_idx == 0 or repeat_header:
            for c in layout.cols:
                items.append(
                    TextItem(c.x + jitter[c.key], y, c.header, bold=True, align=c.align)
                )
        y += _LH + 2
        for row in page.rows:
            for c in layout.cols:
                text = row.get(c.key, "")
                if text:
                    items.append(TextItem(c.x + jitter[c.key], y, text, align=c.align))
            if "_text" in row:
                d = layout.col("description")
                items.append(TextItem(d.x + jitter["description"], y, row["_text"]))
            y += _LH
        items.append(TextItem(36, _FOOTER, f"Page {p_idx + 1} of {n}", size=7.5))
        out.append(PagePlan(tuple(items)))
    return RenderPlan(pages=tuple(out), title=f"{layout.bank} statement")


# ------------------------------------------------------------------ helpers


def _label_row(label: str, value: str, value_key: str = "balance") -> Row:
    return {"_text": label, value_key: value}


def _dmy_slash_yy(d: date) -> str:
    return d.strftime("%d/%m/%y")


# ------------------------------------------------------------------ layouts


def _ledger_cells(t: Txn, lay: Layout) -> Row:
    assert t.balance is not None
    return {
        "posted": lay.fmt_date(t.posted),
        "reference": t.reference or "",
        "value_date": lay.fmt_date(t.value_date or t.posted),
        "debit": fmt_dot(t.debit, indian=True) if t.debit else "",
        "credit": fmt_dot(t.credit, indian=True) if t.credit else "",
        "balance": fmt_dot(t.balance, indian=True),
    }


LEDGER_SPLIT = Layout(
    id="ledger_split",
    bank="LARKSPUR BANK",
    currency="INR",
    with_reference=True,
    cols=(
        Col("posted", "Date", 28),
        Col("description", "Narration", 66),
        Col("reference", "Chq./Ref.No.", 222),
        Col("value_date", "Value Dt", 300),
        Col("debit", "Withdrawal Amt.", 402, Align.RIGHT),
        Col("credit", "Deposit Amt.", 478, Align.RIGHT),
        Col("balance", "Closing Balance", 567, Align.RIGHT),
    ),
    fmt_date=_dmy_slash_yy,
    fmt_period_date=lambda d: d.strftime("%d/%m/%Y"),
    header_lines=lambda s, acct, lay: [
        "Statement of Account",
        "Account Holder : MR A SAMPLE",
        f"Account No : {acct}",
        f"Statement From : {lay.fmt_period_date(s.period_start)} To : {lay.fmt_period_date(s.period_end)}",
        "Currency : INR",
    ],
    cells=_ledger_cells,
    fmt_balance=lambda v: fmt_dot(v, indian=True),
    end_rows=lambda s, lay: [
        {"_text": "STATEMENT SUMMARY"},
        {"_text": f"Opening Balance : {fmt_dot(s.opening_balance, indian=True)}"},
        {"_text": f"Closing Bal : {fmt_dot(s.closing_balance, indian=True)}"},
        {
            "_text": f"Dr Count : {sum(1 for t in s.transactions if t.debit)}  Cr Count : {sum(1 for t in s.transactions if t.credit)}"
        },
    ],
)


def _signed(v: Decimal) -> str:
    return fmt_dot(v)


SIGNED_SINGLE = Layout(
    id="signed_single",
    bank="HARBOR FEDERAL CREDIT UNION",
    currency="USD",
    cols=(
        Col("posted", "Date", 40),
        Col("description", "Description", 100),
        Col("amount", "Amount", 440, Align.RIGHT),
        Col("balance", "Balance", 540, Align.RIGHT),
    ),
    fmt_date=lambda d: d.strftime("%m/%d/%Y"),
    fmt_period_date=lambda d: d.strftime("%m/%d/%Y"),
    header_lines=lambda s, acct, lay: [
        "Account Statement",
        f"Member Account Number: {acct}",
        f"Statement Period: {lay.fmt_period_date(s.period_start)} - {lay.fmt_period_date(s.period_end)}",
        "All amounts in USD",
    ],
    top_summary=lambda s, lay: [
        f"Beginning Balance ${fmt_dot(s.opening_balance)}",
        f"Deposits and Credits ${fmt_dot(sum((t.credit for t in s.transactions), Decimal(0)))}",
        f"Withdrawals and Debits ${fmt_dot(sum((t.debit for t in s.transactions), Decimal(0)))}",
        f"Ending Balance ${fmt_dot(s.closing_balance)}",
    ],
    cells=lambda t, lay: {
        "posted": lay.fmt_date(t.posted),
        "amount": ("-" if t.debit else "") + fmt_dot(t.amount),
        "balance": fmt_dot(t.balance or Decimal(0)),
    },
    fmt_balance=fmt_dot,
)


def _drcr(v: Decimal, sfx: str) -> str:
    return f"{fmt_dot(v, indian=True)} {sfx}"


DRCR_SUFFIX = Layout(
    id="drcr_suffix",
    bank="MISTRAL CO-OPERATIVE BANK",
    currency="INR",
    date_carry_forward=True,
    cols=(
        Col("posted", "Date", 40),
        Col("description", "Particulars", 95),
        Col("amount", "Amount (INR)", 455, Align.RIGHT),
        Col("balance", "Balance (INR)", 560, Align.RIGHT),
    ),
    fmt_date=lambda d: d.strftime("%d %b"),
    fmt_period_date=lambda d: d.strftime("%d %b %Y"),
    header_lines=lambda s, acct, lay: [
        "Account Statement",
        f"A/c No. {acct}",
        f"Period: {lay.fmt_period_date(s.period_start)} to {lay.fmt_period_date(s.period_end)}",
        "Currency INR",
    ],
    cells=lambda t, lay: {
        "posted": lay.fmt_date(t.posted),
        "amount": _drcr(t.amount, "Dr" if t.debit else "Cr"),
        "balance": _drcr(t.balance or Decimal(0), "Cr"),
    },
    fmt_balance=lambda v: _drcr(v, "Cr"),
    pre_table=lambda s, lay: [
        _label_row("Balance B/F", _drcr(s.opening_balance, "Cr"))
    ],
    end_rows=lambda s, lay: [
        _label_row("Closing Balance", _drcr(s.closing_balance, "Cr"))
    ],
)


PAREN_NEGATIVE = Layout(
    id="paren_negative",
    bank="AURELIA BANK AG",
    currency="EUR",
    cols=(
        Col("posted", "Booking date", 36),
        Col("description", "Transaction details", 110),
        Col("amount", "Amount (EUR)", 450, Align.RIGHT),
        Col("balance", "Balance (EUR)", 555, Align.RIGHT),
    ),
    fmt_date=lambda d: d.strftime("%d.%m.%Y"),
    fmt_period_date=lambda d: d.strftime("%d.%m.%Y"),
    header_lines=lambda s, acct, lay: [
        "Account statement",
        f"IBAN DE00 1234 {acct[:4]} {acct[4:8]} {acct[8:]}",
        f"Period {lay.fmt_period_date(s.period_start)} - {lay.fmt_period_date(s.period_end)}",
        "Currency: EUR",
    ],
    top_summary=lambda s, lay: [f"Previous balance {fmt_eu(s.opening_balance)}"],
    cells=lambda t, lay: {
        "posted": lay.fmt_date(t.posted),
        "amount": f"({fmt_eu(t.amount)})" if t.debit else fmt_eu(t.amount),
        "balance": fmt_eu(t.balance or Decimal(0)),
    },
    fmt_balance=fmt_eu,
    end_rows=lambda s, lay: [{"_text": f"New balance {fmt_eu(s.closing_balance)}"}],
)


def _zero_cells(t: Txn, lay: Layout) -> Row:
    return {
        "posted": lay.fmt_date(t.posted),
        "debit": fmt_dot(t.debit),  # INV-10 trap: the empty leg prints 0.00
        "credit": fmt_dot(t.credit),
        "balance": fmt_dot(t.balance or Decimal(0)),
    }


def _zero_close(txns: list[Txn], bal: Decimal, last: bool, lay: Layout) -> list[Row]:
    rows = [
        {
            "_text": "Page total",
            "debit": fmt_dot(sum((t.debit for t in txns), Decimal(0))),
            "credit": fmt_dot(sum((t.credit for t in txns), Decimal(0))),
        }
    ]
    if not last:
        rows.append(_label_row("Balance carried forward", fmt_dot(bal)))
    return rows


SPLIT_ZERO_FILLED = Layout(
    id="split_zero_filled",
    bank="THISTLE & CO PRIVATE BANKING",
    currency="GBP",
    cols=(
        Col("posted", "Date", 36),
        Col("description", "Details", 100),
        Col("debit", "Debit", 390, Align.RIGHT),
        Col("credit", "Credit", 465, Align.RIGHT),
        Col("balance", "Balance", 555, Align.RIGHT),
    ),
    fmt_date=lambda d: d.isoformat(),
    fmt_period_date=lambda d: d.isoformat(),
    header_lines=lambda s, acct, lay: [
        "Current account statement",
        f"Sort code 12-34-56 Account {acct[-8:]}",
        f"From {s.period_start.isoformat()} to {s.period_end.isoformat()}",
        "Currency GBP",
    ],
    cells=_zero_cells,
    fmt_balance=fmt_dot,
    pre_table=lambda s, lay: [
        _label_row("Balance brought forward", fmt_dot(s.opening_balance))
    ],
    page_open=lambda bal, lay: [_label_row("Balance brought forward", fmt_dot(bal))],
    page_close=_zero_close,
    end_rows=lambda s, lay: [_label_row("Closing balance", fmt_dot(s.closing_balance))],
)


NO_BALANCE = Layout(
    id="no_balance",
    bank="PEREGRINE BANK",
    currency="INR",
    balance_policy=BalancePolicy.NONE,
    cols=(
        Col("posted", "Txn Date", 36),
        Col("description", "Description", 105),
        Col("debit", "Withdrawals", 455, Align.RIGHT),
        Col("credit", "Deposits", 555, Align.RIGHT),
    ),
    fmt_date=lambda d: d.strftime("%d-%b-%Y"),
    fmt_period_date=lambda d: d.strftime("%d-%b-%Y"),
    header_lines=lambda s, acct, lay: [
        "Transaction Statement",
        f"Account: {acct}",
        f"Period: {lay.fmt_period_date(s.period_start)} to {lay.fmt_period_date(s.period_end)}",
        "Currency: INR",
    ],
    cells=lambda t, lay: {
        "posted": lay.fmt_date(t.posted),
        "debit": fmt_dot(t.debit, indian=True) if t.debit else "",
        "credit": fmt_dot(t.credit, indian=True) if t.credit else "",
    },
    fmt_balance=lambda v: fmt_dot(v, indian=True),
    end_rows=lambda s, lay: [
        {"_text": f"Opening balance {fmt_dot(s.opening_balance, indian=True)}"},
        {
            "_text": f"Total withdrawals {fmt_dot(sum((t.debit for t in s.transactions), Decimal(0)), indian=True)}"
        },
        {
            "_text": f"Total deposits {fmt_dot(sum((t.credit for t in s.transactions), Decimal(0)), indian=True)}"
        },
        {"_text": f"Closing balance {fmt_dot(s.closing_balance, indian=True)}"},
    ],
)


LAYOUTS: dict[str, Layout] = {
    lay.id: lay
    for lay in (
        LEDGER_SPLIT,
        SIGNED_SINGLE,
        DRCR_SUFFIX,
        PAREN_NEGATIVE,
        SPLIT_ZERO_FILLED,
        NO_BALANCE,
    )
}


def _drift(base: Layout, renames: dict[str, str], drop: tuple[str, ...] = ()) -> Layout:
    """The same bank after a template change: renamed headers, dropped columns.

    This is how positional and header-keyed parsers break in production: the
    numbers are unchanged, the furniture around them moved (risk R1).
    """
    cols = tuple(
        replace(c, header=renames.get(c.key, c.header))
        for c in base.cols
        if c.key not in drop
    )
    return replace(base, id=f"{base.id}_v2", cols=cols)


DRIFTED: dict[str, Layout] = {
    lay.id: lay
    for lay in (
        _drift(
            LEDGER_SPLIT,
            {"description": "Description", "debit": "Debit", "credit": "Credit"},
            drop=("value_date",),
        ),
        _drift(
            SIGNED_SINGLE, {"description": "Details", "amount": "Transaction Amount"}
        ),
        _drift(DRCR_SUFFIX, {"description": "Narration", "posted": "Txn Date"}),
        _drift(PAREN_NEGATIVE, {"posted": "Date", "description": "Details"}),
    )
}
LAYOUTS.update(DRIFTED)

# Layouts with a profile in profiles/ at the start of the project, the two
# held back entirely to measure Tier 2 (H3) and onboarding (H4), and the
# drifted templates of the profiled four.
PROFILED = ("ledger_split", "signed_single", "drcr_suffix", "paren_negative")
HELD_BACK = ("split_zero_filled", "no_balance")
DRIFT = tuple(DRIFTED)
