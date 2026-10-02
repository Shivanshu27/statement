"""Errors as values (BUILD-PLAN §C8).

Expected failures — a malformed PDF, an unknown layout, a broken chain — are
data the pipeline branches on. Exceptions are reserved for bugs.
"""

from __future__ import annotations

from dataclasses import dataclass

from statement.domain.reasons import Reason


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Fail:
    reasons: tuple[Reason, ...]

    def __init__(self, *reasons: Reason) -> None:
        if not reasons:
            raise ValueError("Fail needs at least one reason")
        object.__setattr__(self, "reasons", tuple(reasons))


type Outcome[T] = Ok[T] | Fail
