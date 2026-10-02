"""L3: does the output agree with ground truth? (BUILD-PLAN §D2)

The headline metric is the **silent-wrong rate**: documents ACCEPTED whose
content disagrees with truth. Coverage is reported beside it as an outcome
and never as something to push up (ADR-0013).

Rows are aligned by LCS over (date, amount, direction), not greedily: two
identical ₹10 payments on the same day are both real, and a greedy matcher
would let one extracted row satisfy both (G5).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from statement.domain.model import Direction, Statement, Txn
from statement.pipeline.run import ParseResult, Verdict

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)

RowKey = tuple[str, Decimal, Direction]


def _key(t: Txn) -> RowKey:
    return (t.posted.isoformat(), t.amount, t.direction)


def norm_desc(text: str) -> str:
    return _PUNCT.sub(" ", text.casefold()).strip()


def lcs_pairs(a: list[RowKey], b: list[RowKey]) -> list[tuple[int, int]]:
    """Index pairs of a longest common subsequence of ``a`` and ``b``."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = (
                dp[i + 1][j + 1] + 1
                if a[i] == b[j]
                else max(dp[i + 1][j], dp[i][j + 1])
            )
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


@dataclass(frozen=True, slots=True)
class RowDiff:
    seq: int
    field: str
    truth: str
    got: str


@dataclass(frozen=True, slots=True)
class DocScore:
    name: str
    layout: str
    verdict: str
    tier: int
    profile_id: str | None
    truth_rows: int
    got_rows: int
    key_matched: int  # rows matching on (date, amount, direction)
    agreed: int  # key match + description + balance
    header_ok: bool  # opening, closing, period, currency
    exact: bool
    silent_wrong: bool
    reasons: tuple[str, ...]
    tokens_in: int
    tokens_out: int
    llm_cached: bool
    first_diffs: tuple[RowDiff, ...] = ()


def score_doc(
    name: str, layout: str, truth: Statement, result: ParseResult
) -> DocScore:
    got = result.statement
    reasons = tuple(sorted({r.code.value for r in result.reasons}))
    usage = (result.tokens_in, result.tokens_out, result.llm_cached)
    if got is None:
        return DocScore(
            name,
            layout,
            result.verdict.value,
            result.tier,
            result.profile_id,
            len(truth.transactions),
            0,
            0,
            0,
            False,
            False,
            False,
            reasons,
            *usage,
        )

    tk = [_key(t) for t in truth.transactions]
    gk = [_key(t) for t in got.transactions]
    pairs = lcs_pairs(tk, gk)
    agreed = 0
    diffs: list[RowDiff] = []
    for i, j in pairs:
        t, g = truth.transactions[i], got.transactions[j]
        ok = True
        if norm_desc(t.description) != norm_desc(g.description):
            ok = False
            diffs.append(RowDiff(t.seq, "description", t.description, g.description))
        if t.balance is not None and t.balance != g.balance:
            ok = False
            diffs.append(RowDiff(t.seq, "balance", str(t.balance), str(g.balance)))
        agreed += ok
    if len(pairs) < len(tk):
        matched = {i for i, _ in pairs}
        missing = next(i for i in range(len(tk)) if i not in matched)
        t = truth.transactions[missing]
        diffs.insert(
            0, RowDiff(t.seq, "row", f"{t.posted} {t.amount} {t.direction}", "missing")
        )

    header_ok = (
        truth.opening_balance == got.opening_balance
        and truth.closing_balance == got.closing_balance
        and truth.period_start == got.period_start
        and truth.period_end == got.period_end
        and truth.currency == got.currency
    )
    exact = header_ok and agreed == len(tk) == len(gk)
    return DocScore(
        name=name,
        layout=layout,
        verdict=result.verdict.value,
        tier=result.tier,
        profile_id=result.profile_id,
        truth_rows=len(tk),
        got_rows=len(gk),
        key_matched=len(pairs),
        agreed=agreed,
        header_ok=header_ok,
        exact=exact,
        silent_wrong=result.verdict is Verdict.ACCEPTED and not exact,
        reasons=reasons,
        tokens_in=usage[0],
        tokens_out=usage[1],
        llm_cached=usage[2],
        first_diffs=tuple(diffs[:3]),
    )


# ------------------------------------------------------------------ aggregate


@dataclass(frozen=True, slots=True)
class Summary:
    docs: int
    accepted: int
    needs_review: int
    rejected: int
    silent_wrong: int
    truth_rows: int
    agreed_rows: int
    exact_docs: int
    tier1_accepted: int
    tier2_accepted: int
    tokens_in: int
    tokens_out: int
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        return self.accepted / self.docs if self.docs else 0.0

    @property
    def silent_wrong_rate(self) -> float:
        return self.silent_wrong / self.accepted if self.accepted else 0.0

    @property
    def row_agreement(self) -> float:
        return self.agreed_rows / self.truth_rows if self.truth_rows else 0.0

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            coverage=round(self.coverage, 4),
            silent_wrong_rate=round(self.silent_wrong_rate, 4),
            row_agreement=round(self.row_agreement, 4),
        )
        return d


def summarise(scores: list[DocScore]) -> Summary:
    reasons: Counter[str] = Counter()
    for s in scores:
        reasons.update(s.reasons)
    return Summary(
        docs=len(scores),
        accepted=sum(s.verdict == Verdict.ACCEPTED for s in scores),
        needs_review=sum(s.verdict == Verdict.NEEDS_REVIEW for s in scores),
        rejected=sum(s.verdict == Verdict.REJECTED for s in scores),
        silent_wrong=sum(s.silent_wrong for s in scores),
        truth_rows=sum(s.truth_rows for s in scores),
        agreed_rows=sum(s.agreed for s in scores),
        exact_docs=sum(s.exact for s in scores),
        tier1_accepted=sum(
            s.verdict == Verdict.ACCEPTED and s.tier == 1 for s in scores
        ),
        tier2_accepted=sum(
            s.verdict == Verdict.ACCEPTED and s.tier == 2 for s in scores
        ),
        tokens_in=sum(s.tokens_in for s in scores),
        tokens_out=sum(s.tokens_out for s in scores),
        reasons=dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def scorecard(scores: list[DocScore], manifest: dict[str, Any]) -> dict[str, Any]:
    by_layout: dict[str, list[DocScore]] = {}
    for s in scores:
        by_layout.setdefault(s.layout, []).append(s)
    return {
        "manifest": manifest,
        "overall": summarise(scores).to_json(),
        "by_layout": {k: summarise(v).to_json() for k, v in sorted(by_layout.items())},
    }
