"""Property tests: invariants hold for any generated ledger; corruptions are caught."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from statement.domain.verify import verify
from statement.evaluate.corrupt import MUTATIONS
from statement.forge.corpus import Split, build
from statement.forge.layouts import LAYOUTS

layouts = st.sampled_from(sorted(LAYOUTS))
seeds = st.integers(min_value=0, max_value=10**6)


@settings(max_examples=60, deadline=None)
@given(layouts, seeds)
def test_any_forged_ledger_verifies(layout: str, seed: int) -> None:
    assert verify(build(layout, seed, Split.DEV).truth).ok


@settings(max_examples=60, deadline=None)
@given(
    layouts,
    seeds,
    st.sampled_from(
        [c for c, (_, det) in MUTATIONS.items() if det and c != "F08_day_month_swapped"]
    ),
)
def test_single_row_corruptions_are_always_detected(
    layout: str, seed: int, code: str
) -> None:
    truth = build(layout, seed, Split.DEV).truth
    mutate, _ = MUTATIONS[code]
    try:
        bad = mutate(truth, random.Random(seed))
    except ValueError:
        return  # refused by the model itself: detected by construction
    if bad is None or bad == truth:
        return
    assert not verify(bad).ok, code
