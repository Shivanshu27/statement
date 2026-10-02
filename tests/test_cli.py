"""The CLI end to end, in a temp dir: forge -> parse/explain -> eval -> diff -> corrupt -> replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from statement.cli.main import app
from tests.conftest import ROOT

runner = CliRunner()


@pytest.mark.slow
def test_cli_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATEMENT_PROFILES", str(ROOT / "profiles"))
    monkeypatch.setenv("STATEMENT_LLM", "none")
    corpus, runs = tmp_path / "c", tmp_path / "runs"

    r = runner.invoke(
        app,
        [
            "forge",
            "--out",
            str(corpus),
            "--n",
            "2",
            "--layouts",
            "ledger_split,no_balance",
        ],
    )
    assert r.exit_code == 0, r.output
    pdf = sorted(corpus.glob("ledger_split-*.pdf"))[0]

    r = runner.invoke(app, ["parse", str(pdf)])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["verdict"] == "ACCEPTED"

    r = runner.invoke(app, ["explain", str(pdf)])
    assert r.exit_code == 0 and "ACCEPTED (tier 1" in r.output

    for _ in range(2):
        r = runner.invoke(
            app, ["eval", str(corpus), "--out", str(runs), "--workers", "1"]
        )
        assert r.exit_code == 0, r.output
        assert "silent-wrong 0" in r.output
    a, b = (
        sorted(runs.iterdir())[:2] if len(list(runs.iterdir())) >= 2 else (None, None)
    )
    if a and b:
        r = runner.invoke(app, ["eval-diff", str(a), str(b)])
        assert r.exit_code == 0 and "overall" in r.output
    card = json.loads((sorted(runs.iterdir())[0] / "scorecard.json").read_text())
    assert card["manifest"]["prompt_hash"] and card["overall"]["docs"] == 4

    r = runner.invoke(
        app, ["corrupt-eval", str(corpus), "--out", str(runs), "--trials", "1"]
    )
    assert r.exit_code == 0 and "detectable classes" in r.output

    dump = tmp_path / "dump.jsonl"
    r = runner.invoke(app, ["replay", str(corpus), "--out", str(dump)])
    assert r.exit_code == 0 and len(dump.read_text().splitlines()) == 4

    r = runner.invoke(app, ["profiles"])
    assert r.exit_code == 0 and "ledger_split" in r.output


def test_parse_exits_nonzero_unless_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STATEMENT_PROFILES", str(ROOT / "profiles"))
    junk = tmp_path / "x.pdf"
    junk.write_bytes(b"not a pdf")
    r = runner.invoke(app, ["parse", str(junk)])
    assert r.exit_code == 2 and '"REJECTED"' in r.output
