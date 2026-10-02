"""The forge: deterministic, truthful, and refuses to draw overlapping text."""

from __future__ import annotations

import pytest

from statement.domain.verify import verify
from statement.forge.corpus import Split, build, generate
from statement.forge.layouts import LAYOUTS, Layout, fmt_dot, fmt_eu, render


def test_number_formats() -> None:
    from decimal import Decimal

    assert fmt_dot(Decimal("1234567.50"), indian=True) == "12,34,567.50"
    assert fmt_dot(Decimal("1234567.50")) == "1,234,567.50"
    assert fmt_eu(Decimal("1234567.50")) == "1.234.567,50"
    assert fmt_dot(Decimal("0")) == "0.00"


def test_plans_are_deterministic() -> None:
    a, b = build("drcr_suffix", 11, Split.DEV), build("drcr_suffix", 11, Split.DEV)
    assert a.plan == b.plan and a.truth == b.truth


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_forge_truth_always_verifies(layout: str) -> None:
    for seed in range(25):
        truth = build(layout, seed, Split.DEV).truth
        assert verify(truth).ok, (layout, seed)


def test_holdout_requires_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        list(generate(Split.HOLDOUT, 1))


def test_holdout_seeds_differ_from_dev() -> None:
    hold = {d.seed for d in generate(Split.HOLDOUT, 5, secret="s3cret")}
    assert all(seed >= 1_000_000 for seed in hold)


def test_overflowing_text_is_a_forge_bug() -> None:
    narrow = LAYOUTS["signed_single"]
    cols = tuple(
        c if c.key != "amount" else type(c)(c.key, c.header, 160, c.align)
        for c in narrow.cols
    )
    squeezed = Layout(
        **{**{f: getattr(narrow, f) for f in narrow.__dataclass_fields__}, "cols": cols}
    )
    truth = build("signed_single", 0, Split.DEV).truth
    with pytest.raises(ValueError, match="overflows"):
        render(truth, squeezed, 0)
