"""The trust ladder (BUILD-PLAN §C3).

    ingest -> text layer -> classify -> Tier 1 -> VERIFY -> ACCEPTED
                                          |  fail / unknown layout
                                          v
                                        Tier 2 -> VERIFY -> ACCEPTED
                                          |  fail / error / budget
                                          v
                                        degrade -> NEEDS_REVIEW

The same verifier, with the same thresholds, judges both tiers. A rescued
document must pass exactly the arithmetic a Tier-1 document does.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from statement.domain.model import Statement
from statement.domain.outcome import Fail
from statement.domain.profile import Profile
from statement.domain.reasons import REJECTING, Code, Reason
from statement.domain.verify import Check, Verification, verify
from statement.extract.tier1 import classify, extract
from statement.ports import Extraction, LlmPort, TextReader
from statement.rescue.tier2 import Budget, rescue


class Verdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Event:
    stage: str
    outcome: str
    ms: float
    detail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseResult:
    doc_id: str
    verdict: Verdict
    statement: Statement | None
    reasons: tuple[Reason, ...]
    tier: int  # highest tier reached: 0 = never got past ingest
    profile_id: str | None
    checks: dict[str, Check] = field(default_factory=dict)
    trace: tuple[Event, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0
    llm_cached: bool = False


@dataclass(frozen=True, slots=True)
class Limits:
    max_bytes: int = 20 * 1024 * 1024


def doc_id_for(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decide(extraction: Extraction, verification: Verification | None) -> Verdict:
    """INV-05: acceptance is a function of the verifier's output, and only that.

    An extraction's own reasons (unparsed rows, ungrounded cells) block
    acceptance too: a statement that verifies but skipped a line it could
    not read is not a statement we can vouch for.
    """
    if extraction.statement is None or verification is None:
        return Verdict.NEEDS_REVIEW
    if verification.ok and not extraction.reasons:
        return Verdict.ACCEPTED
    return Verdict.NEEDS_REVIEW


class Pipeline:
    def __init__(
        self,
        reader: TextReader,
        profiles: Sequence[Profile],
        llm: LlmPort | None = None,
        *,
        limits: Limits = Limits(),
        budget: Budget = Budget(),
    ) -> None:
        self._reader = reader
        self._profiles = tuple(profiles)
        self._llm = llm
        self._limits = limits
        self._budget = budget

    def parse(self, data: bytes) -> ParseResult:
        trace: list[Event] = []
        doc_id = doc_id_for(data)

        def mark(stage: str, outcome: str, t0: float, *detail: str) -> None:
            trace.append(
                Event(
                    stage, outcome, round((time.perf_counter() - t0) * 1000, 2), detail
                )
            )

        # ① ingest
        t0 = time.perf_counter()
        if len(data) > self._limits.max_bytes:
            return self._rejected(
                doc_id, Reason(Code.TOO_LARGE, f"{len(data)} bytes"), trace
            )
        if not data.startswith(b"%PDF-"):
            return self._rejected(doc_id, Reason(Code.NOT_PDF), trace)
        mark("ingest", "ok", t0)

        # ② text layer
        t0 = time.perf_counter()
        read = self._reader.read(data, doc_id)
        if isinstance(read, Fail):
            mark("text_layer", "fail", t0, *map(str, read.reasons))
            if any(r.code in REJECTING for r in read.reasons):
                return self._rejected(doc_id, read.reasons[0], trace)
            return ParseResult(
                doc_id,
                Verdict.NEEDS_REVIEW,
                None,
                read.reasons,
                0,
                None,
                trace=tuple(trace),
            )
        doc = read.value
        mark(
            "text_layer",
            "ok",
            t0,
            f"{len(doc.pages)} pages",
            f"{len(doc.lines())} lines",
        )

        # ③ classify + ④ tier 1 + ⑤ verify
        t0 = time.perf_counter()
        profile_id: str | None = None
        cls = classify(doc, self._profiles)
        tier1: Extraction
        if isinstance(cls, Fail):
            mark("classify", "unknown", t0, *map(str, cls.reasons))
            tier1 = Extraction(None, cls.reasons)
        else:
            profile = cls.value
            profile_id = profile.id
            mark("classify", profile.id, t0, f"v{profile.version}")
            t0 = time.perf_counter()
            tier1 = extract(doc, profile)
            mark(
                "tier1",
                "statement" if tier1.statement else "none",
                t0,
                *map(str, tier1.reasons),
            )
            v1 = self._verify(tier1, profile.tolerance_days, trace)
            if decide(tier1, v1) is Verdict.ACCEPTED:
                assert tier1.statement is not None and v1 is not None
                return ParseResult(
                    doc_id,
                    Verdict.ACCEPTED,
                    tier1.statement,
                    (),
                    1,
                    profile_id,
                    v1.checks,
                    tuple(trace),
                )
            tier1 = Extraction(
                tier1.statement, (*tier1.reasons, *(v1.reasons if v1 else ()))
            )

        # ⑥ tier 2 + ⑦ verify
        if self._llm is None:
            reasons = (
                *tier1.reasons,
                Reason(Code.RESCUE_UNAVAILABLE, "no LLM configured"),
            )
            return self._degrade(doc_id, tier1, reasons, 1, profile_id, trace)
        t0 = time.perf_counter()
        try:
            tier2 = rescue(doc, self._llm, self._budget)
        except Exception as exc:
            # INV-12: the one deliberate broad except. A bug in the rescue path
            # must degrade to the Tier-1 result, never escape or upgrade it.
            mark("tier2", "error", t0, repr(exc))
            reasons = (*tier1.reasons, Reason(Code.RESCUE_ERROR, type(exc).__name__))
            return self._degrade(doc_id, tier1, reasons, 2, profile_id, trace)
        mark(
            "tier2",
            "statement" if tier2.statement else "none",
            t0,
            *map(str, tier2.reasons),
        )
        v2 = self._verify(tier2, 0, trace)
        if decide(tier2, v2) is Verdict.ACCEPTED:
            assert tier2.statement is not None and v2 is not None
            result = ParseResult(
                doc_id,
                Verdict.ACCEPTED,
                tier2.statement,
                (),
                2,
                profile_id,
                v2.checks,
                tuple(trace),
            )
        else:
            # ⑧ degrade: show the best available read, never as trusted
            reasons = (*tier1.reasons, *tier2.reasons, *(v2.reasons if v2 else ()))
            best = tier2 if tier2.statement is not None else tier1
            result = self._degrade(doc_id, best, reasons, 2, profile_id, trace)
        return replace(
            result,
            tokens_in=tier2.tokens_in,
            tokens_out=tier2.tokens_out,
            llm_cached=tier2.cached,
        )

    # ------------------------------------------------------------------

    def _verify(
        self, ext: Extraction, tolerance_days: int, trace: list[Event]
    ) -> Verification | None:
        if ext.statement is None:
            return None
        t0 = time.perf_counter()
        v = verify(ext.statement, tolerance_days=tolerance_days)
        trace.append(
            Event(
                "verify",
                "pass" if v.ok else "fail",
                round((time.perf_counter() - t0) * 1000, 2),
                tuple(f"{k}={c}" for k, c in v.checks.items())
                + tuple(map(str, v.reasons)),
            )
        )
        return v

    @staticmethod
    def _rejected(doc_id: str, reason: Reason, trace: list[Event]) -> ParseResult:
        trace.append(Event("ingest", "rejected", 0.0, (str(reason),)))
        return ParseResult(
            doc_id, Verdict.REJECTED, None, (reason,), 0, None, trace=tuple(trace)
        )

    @staticmethod
    def _degrade(
        doc_id: str,
        best: Extraction,
        reasons: tuple[Reason, ...],
        tier: int,
        profile_id: str | None,
        trace: list[Event],
    ) -> ParseResult:
        trace.append(
            Event(
                "verdict",
                Verdict.NEEDS_REVIEW,
                0.0,
                tuple(sorted({r.code for r in reasons})),
            )
        )
        return ParseResult(
            doc_id,
            Verdict.NEEDS_REVIEW,
            best.statement,
            reasons,
            tier,
            profile_id,
            trace=tuple(trace),
        )
