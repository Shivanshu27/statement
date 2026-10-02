"""Golden round trip: forge -> PDF -> Tier 1 == ground truth, for every profiled layout."""

from __future__ import annotations

import pytest

from statement.forge.layouts import HELD_BACK, PROFILED
from statement.pipeline.run import Verdict
from tests.conftest import pipeline, rows_of, sample


@pytest.mark.slow
@pytest.mark.parametrize("layout", PROFILED)
@pytest.mark.parametrize("seed", [0, 7, 21, 33])
def test_profiled_layouts_round_trip_exactly(profiles, layout: str, seed: int) -> None:
    s = sample(layout, seed)
    r = pipeline(profiles).parse(s.pdf)
    assert r.verdict is Verdict.ACCEPTED, [str(x) for x in r.reasons]
    assert r.tier == 1 and r.profile_id == layout
    assert r.statement is not None
    assert rows_of(r.statement) == rows_of(s.truth)
    assert r.statement.opening_balance == s.truth.opening_balance
    assert r.statement.closing_balance == s.truth.closing_balance
    assert (r.statement.period_start, r.statement.period_end) == (
        s.truth.period_start,
        s.truth.period_end,
    )


@pytest.mark.parametrize("layout", HELD_BACK)
def test_held_back_layouts_are_never_accepted_without_a_profile(
    profiles, layout: str
) -> None:
    r = pipeline(profiles).parse(sample(layout, 0).pdf)
    assert r.verdict is Verdict.NEEDS_REVIEW
    codes = {x.code.value for x in r.reasons}
    assert {"UNKNOWN_LAYOUT", "RESCUE_UNAVAILABLE"} <= codes
