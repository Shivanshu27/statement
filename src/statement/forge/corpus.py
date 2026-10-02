"""Corpus splits (BUILD-PLAN §D1).

| split    | layouts     | seeds                          | who may read it   |
|----------|-------------|--------------------------------|-------------------|
| dev      | profiled    | 0..n-1                         | everyone          |
| unknown  | held back   | 0..n-1                         | everyone          |
| drift    | profiled v2 | 0..n-1                         | everyone          |
| holdout  | all         | derived from a secret          | CI only (§E3)     |
| canary   | all         | fixed, 10_000+                 | the drift canary  |
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

from statement.domain.model import Statement
from statement.forge.layouts import DRIFT, HELD_BACK, LAYOUTS, PROFILED, render
from statement.forge.ledger import simulate
from statement.forge.plan import RenderPlan

FORGE_VERSION = 1


class Split(StrEnum):
    DEV = "dev"
    UNKNOWN = "unknown"
    DRIFT = "drift"
    HOLDOUT = "holdout"
    CANARY = "canary"


@dataclass(frozen=True, slots=True)
class ForgeDoc:
    name: str
    layout: str
    seed: int
    split: Split
    plan: RenderPlan
    truth: Statement  # doc_id is filled in once the PDF bytes exist

    def meta(self) -> dict[str, object]:
        return {
            "layout": self.layout,
            "seed": self.seed,
            "split": self.split.value,
            "forge_version": FORGE_VERSION,
        }


def _holdout_seed(secret: str, layout: str, i: int) -> int:
    digest = hashlib.sha256(f"{secret}:{layout}:{i}".encode()).digest()
    return 1_000_000 + int.from_bytes(digest[:4], "big")


def build(layout_id: str, seed: int, split: Split) -> ForgeDoc:
    lay = LAYOUTS[layout_id]
    truth = simulate(
        layout_id,
        seed,
        lay.currency,
        with_reference=lay.with_reference,
        balance_policy=lay.balance_policy,
    )
    return ForgeDoc(
        name=f"{layout_id}-{seed:07d}",
        layout=layout_id,
        seed=seed,
        split=split,
        plan=render(truth, lay, seed),
        truth=truth,
    )


def generate(
    split: Split,
    n: int,
    *,
    layouts: tuple[str, ...] | None = None,
    secret: str | None = None,
) -> Iterator[ForgeDoc]:
    if split is Split.HOLDOUT and not secret:
        raise ValueError(
            "the holdout is generated from a secret (STATEMENT_HOLDOUT_SECRET)"
        )
    default = {
        Split.DEV: PROFILED,
        Split.UNKNOWN: HELD_BACK,
        Split.DRIFT: DRIFT,
        Split.HOLDOUT: PROFILED + HELD_BACK,
        Split.CANARY: PROFILED + HELD_BACK,
    }[split]
    for layout_id in layouts or default:
        if layout_id not in LAYOUTS:
            raise ValueError(f"unknown layout {layout_id!r}")
        for i in range(n):
            if split is Split.HOLDOUT:
                assert secret is not None
                seed = _holdout_seed(secret, layout_id, i)
            elif split is Split.CANARY:
                seed = 10_000 + i
            else:
                seed = i
            yield build(layout_id, seed, split)
