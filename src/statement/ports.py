"""The application's view of the outside world (BUILD-PLAN §C4).

The pipeline depends on these protocols, never on an adapter. Only the
composition root (``cli/composition.py``) knows which adapter is behind
each one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from statement.domain.model import Statement
from statement.domain.outcome import Outcome
from statement.domain.profile import Profile
from statement.domain.reasons import Reason
from statement.domain.text import TextDocument


class TextReader(Protocol):
    """Bytes -> words with boxes. Owns the PDF-is-untrusted-input limits (§F4)."""

    def read(self, data: bytes, doc_id: str) -> Outcome[TextDocument]: ...


@dataclass(frozen=True, slots=True)
class LlmRequest:
    system: str
    user: str
    template_hash: (
        str  # part of the cache key: edited prompts must not replay stale answers
    )
    payload_hash: str
    max_tokens: int


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cached: bool = False


class LlmPort(Protocol):
    @property
    def model_id(self) -> str: ...

    def complete(self, req: LlmRequest) -> Outcome[LlmResponse]: ...


class ProfileSource(Protocol):
    def profiles(self) -> Sequence[Profile]: ...


@dataclass(frozen=True, slots=True)
class Extraction:
    """What a tier produced: the best statement it could build, and why it's doubtful.

    ``statement`` may be present alongside reasons — a partial read is still
    shown to a reviewer as ``NEEDS_REVIEW``, never discarded and never trusted.
    """

    statement: Statement | None
    reasons: tuple[Reason, ...]
    tokens_in: int = 0
    tokens_out: int = 0
    cached: bool = False
