"""The drift canary compares live readings over time, not against truth."""

from __future__ import annotations

import json

from statement.evaluate.canary import compare, observe
from statement.forge.layouts import LAYOUTS
from tests.conftest import ScriptedLlm, oracle_payload, read, reply, sample


def test_identical_days_report_no_change() -> None:
    s = sample("split_zero_filled", 0)
    doc = read(s.pdf)
    payload = oracle_payload(doc, s.truth, LAYOUTS["split_zero_filled"])
    day1 = observe([("a", doc)], ScriptedLlm(reply(payload)))
    day2 = observe([("a", doc)], ScriptedLlm(reply(payload)))
    assert compare(day1, day2) == []


def test_a_flipped_cell_is_reported_with_its_location() -> None:
    s = sample("split_zero_filled", 0)
    doc = read(s.pdf)
    payload = oracle_payload(doc, s.truth, LAYOUTS["split_zero_filled"])
    day1 = observe([("a", doc)], ScriptedLlm(reply(payload)))
    drifted = json.loads(json.dumps(payload))
    drifted["rows"][3]["balance"] = None  # the model silently stops copying one cell
    del drifted["rows"][5]
    day2 = observe([("a", doc)], ScriptedLlm(reply(drifted)))
    changes = compare(day1, day2)
    assert any(c.where == "rows" for c in changes)
    assert any(c.where == "rows[3].balance" for c in changes)


def test_provider_errors_are_observations_too() -> None:
    from tests.conftest import failing

    s = sample("no_balance", 0)
    doc = read(s.pdf)
    obs = observe([("a", doc)], ScriptedLlm(failing()))
    assert obs["a"] == {"error": ["RESCUE_ERROR"]}
