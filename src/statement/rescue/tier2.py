"""Tier 2: the LLM rescue, run only when Tier 1 could not verify a document.

The model returns cells; grounding drops any cell not printed on the page;
reading rules are *inferred from the grounded cells by code*; the shared
deterministic assembler builds the statement. The model never produces the
final object and never sees the verifier.
"""

from __future__ import annotations

from dataclasses import dataclass

from statement.domain.assemble import AmountMode, RawDoc, RawRow, ReadingRules, assemble
from statement.domain.model import BalancePolicy, Provenance, Statement
from statement.domain.outcome import Fail, Ok, Outcome
from statement.domain.parsing import (
    Marker,
    infer_date_format,
    infer_number_locale,
    parse_amount,
)
from statement.domain.reasons import Code, Reason
from statement.domain.text import TextDocument
from statement.ports import Extraction, LlmPort, LlmRequest
from statement.rescue.grounding import ground
from statement.rescue.prompt import SYSTEM, TEMPLATE_HASH, build_user, payload_hash
from statement.rescue.schema import LlmDoc, parse_response


@dataclass(frozen=True, slots=True)
class Budget:
    max_lines: int = 800  # beyond this a statement needs chunking, not a bigger prompt
    max_tokens: int = 8000  # headroom for models that spend output on reasoning (G5)


def _infer_rules(llm: LlmDoc) -> Outcome[ReadingRules]:
    money = [
        v
        for r in llm.rows
        for v in (r.debit, r.credit, r.amount, r.balance)
        if v is not None and v.strip()
    ] + [v for v in (llm.opening_balance, llm.closing_balance) if v]
    locale = infer_number_locale(money)
    if locale is None:
        return Fail(Reason(Code.UNPARSEABLE_MONEY, "cannot infer number locale"))

    uses_amount = any(r.amount for r in llm.rows)
    uses_split = any(r.debit or r.credit for r in llm.rows)
    if uses_amount and uses_split:
        return Fail(Reason(Code.RESCUE_UNPARSEABLE, "rows mix amount and debit/credit"))
    mode = AmountMode.SPLIT
    if uses_amount:
        markers = set()
        for r in llm.rows:
            if r.amount:
                p = parse_amount(r.amount, locale)
                if isinstance(p, Ok):
                    markers.add(p.value.marker)
        mode = (
            AmountMode.SUFFIX if markers & {Marker.DR, Marker.CR} else AmountMode.SIGNED
        )

    with_balance = sum(1 for r in llm.rows if r.balance)
    # Mixed presence is not a third policy: it is a partial read, and
    # EVERY_ROW makes the verifier say so (BALANCE_MISSING).
    policy = BalancePolicy.NONE if with_balance == 0 else BalancePolicy.EVERY_ROW

    if not (llm.period_start and llm.period_end):
        return Fail(Reason(Code.PERIOD_MISSING))
    fmts = infer_date_format(
        (llm.period_start, llm.period_end), [r.date for r in llm.rows]
    )
    if isinstance(fmts, Fail):
        return fmts
    period_fmt, row_fmt = fmts.value
    return Ok(
        ReadingRules(
            locale=locale,
            period_format=period_fmt,
            row_date_format=row_fmt,
            amount_mode=mode,
            balance_policy=policy,
        )
    )


def rescue(doc: TextDocument, llm: LlmPort, budget: Budget = Budget()) -> Extraction:
    n_lines = len(doc.lines())
    if n_lines > budget.max_lines:
        return Extraction(None, (Reason(Code.RESCUE_BUDGET, f"{n_lines} lines"),))

    req = LlmRequest(
        system=SYSTEM,
        user=build_user(doc),
        template_hash=TEMPLATE_HASH,
        payload_hash=payload_hash(doc),
        max_tokens=budget.max_tokens,
    )
    reply = llm.complete(req)
    if isinstance(reply, Fail):
        return Extraction(None, reply.reasons)
    resp = reply.value

    def done(stmt: Statement | None, *reasons: Reason) -> Extraction:
        return Extraction(
            stmt,
            tuple(reasons),
            tokens_in=resp.input_tokens,
            tokens_out=resp.output_tokens,
            cached=resp.cached,
        )

    parsed = parse_response(resp.text)
    if isinstance(parsed, Fail):
        return done(None, *parsed.reasons)

    grounded = ground(parsed.value, doc)
    rules = _infer_rules(grounded.doc)
    if isinstance(rules, Fail):
        return done(None, *grounded.reasons, *rules.reasons)

    g = grounded.doc
    lines = doc.line_map()
    raw = RawDoc(
        doc_id=doc.doc_id,
        currency=g.currency.strip().upper() if g.currency else None,
        account=None,
        period=(g.period_start, g.period_end)
        if g.period_start and g.period_end
        else None,
        opening=g.opening_balance,
        closing=g.closing_balance,
        rows=tuple(
            RawRow(
                line_ids=r.line_ids,
                page=lines[r.line_ids[0]].page,
                posted=r.date,
                description=r.description,
                debit=r.debit,
                credit=r.credit,
                amount=r.amount,
                balance=r.balance,
            )
            for r in g.rows
        ),
    )
    provenance = Provenance(tier=2, model_id=resp.model_id, prompt_hash=TEMPLATE_HASH)
    out = assemble(raw, rules.value, provenance)
    if isinstance(out, Fail):
        return done(None, *grounded.reasons, *out.reasons)
    return done(out.value, *grounded.reasons)
