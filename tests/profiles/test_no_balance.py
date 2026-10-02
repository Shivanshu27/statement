"""Onboarded profile `no_balance`: round trip on fresh seeds (written by /add-layout)."""

from __future__ import annotations

import pytest

from statement.pipeline.run import Verdict
from tests.conftest import pipeline, rows_of, sample


@pytest.mark.slow
@pytest.mark.parametrize("seed", [100, 101, 102, 103, 104])
def test_no_balance_round_trips(all_profiles, seed: int) -> None:
    s = sample("no_balance", seed)
    r = pipeline(all_profiles).parse(s.pdf)
    assert r.verdict is Verdict.ACCEPTED, [str(x) for x in r.reasons]
    assert r.profile_id == "no_balance" and r.tier == 1
    assert r.statement is not None and rows_of(r.statement) == rows_of(s.truth)
